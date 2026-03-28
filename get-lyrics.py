import os
import sys
import zhconv
from pathlib import Path
from tinytag import TinyTag
from syncedlyrics import search

from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3

import re
import shutil
from rich.console import Console
from rich.table import Table
from rich import box

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout import Layout
from prompt_toolkit.styles import Style

console = Console()

def format_netease_lyrics(lrc):
    lrc = lrc.split('\n')

    # Remove credits at the beginning and end of lyrics
    pattern = re.compile(r'\[.*\] .+ : .+')
    while lrc and pattern.match(lrc[0]):
        lrc.pop(0)
    if not lrc[-1]:
        lrc.pop()
    while lrc and pattern.match(lrc[-1]):
        lrc.pop()

    lrc = '\n'.join(lrc)

    # Replace right single quotation mark with apostrophe
    lrc = lrc.replace("’", "'")

    # Convert simplified Chinese to traditional Chinese
    lrc = zhconv.convert(lrc, 'zh-tw')
    return lrc


def save_lyrics(lrc, save_path):
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(lrc)
    console.print(f"  [green]✅ Saved[/green] [dim]{save_path.name}[/dim]")
    return lrc


def try_query(query, save_path):
    console.print(f"  [dim]🔍 {query}[/dim]")
    lrc = search(query, synced_only=True, providers=["Lrclib"])

    if lrc == "[instrumental]":
        return -1

    if lrc:
        return save_lyrics(lrc, save_path)

    lrc = search(query, synced_only=True, providers=["NetEase"])
    if lrc:
        lrc = format_netease_lyrics(lrc)
        return save_lyrics(lrc, save_path)

    return None


def remove_txt_if_exists(path):
    if path.exists():
        os.remove(path)
        console.print(f"    [dim]🗑️  Removed {path.name}[/dim]")


def set_language_instrumental(file_path):
    ext = file_path.suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(file_path)
            audio["language"] = ["Instrumental"]
            audio.save()
        elif ext == ".mp3":
            audio = EasyMP3(file_path)
            audio["language"] = ["Instrumental"]
            audio.save()
    except Exception as e:
        console.print(f"  [yellow]⚠️  Failed to set language tag on[/yellow] [bold]{file_path.name}[/bold][yellow]: {e}[/yellow]")


def get_lyrics_for_album(album_path):
    album_name = album_path.name
    files = list(album_path.glob("*.flac")) + list(album_path.glob("*.m4a")) + list(album_path.glob("*.mp3"))

    if not files:
        return

    tracks = []
    console.rule(f"[bold cyan]💿 {album_name}[/bold cyan]")
    console.print()

    for file_name in sorted(files):
        tags = TinyTag.get(file_name)

        title = tags.title
        artist = " ".join([tags.artist] + tags.other.get("artist", []))
        album = tags.album

        console.print(f"  [bold]{file_name.stem}[/bold]")

        # File is already marked as instrumental, skip it
        if tags.other.get("language", [""])[0] == "Instrumental":
            console.print(f"    [dim]🚫 Already marked instrumental, skipping[/dim]")
            tracks.append(("🚫", file_name.stem))
            continue

        # Lyrics file already exists, skip it
        save_path = album_path / f"{file_name.stem}.lrc"
        if save_path.exists():
            console.print(f"    [dim]⏭️  Lyrics already exist[/dim]")
            tracks.append(("⏭️", file_name.stem))

            # Remove .txt lyric files
            remove_txt_if_exists(album_path / f"{file_name.stem}.txt")
            continue

        lrc = try_query(f"{title} {artist} {album}", save_path)
        if not lrc:
            lrc = try_query(f"{title} {artist}", save_path)

        if lrc == -1:
            set_language_instrumental(file_name)
            console.print(f"    [blue]🎸 Instrumental — tagged accordingly[/blue]")
            tracks.append(("🎸", file_name.stem))
        else:
            if not lrc:
                console.print(f"    [red]❌ No lyrics found[/red]")
            tracks.append(("✅" if lrc else "❌", file_name.stem))

        # Remove .txt lyric files
        if lrc:
            remove_txt_if_exists(album_path / f"{file_name.stem}.txt")

    console.print()
    table = Table(title=f"[bold]{album_name}[/bold]", box=box.ROUNDED, show_header=False, padding=(0, 1))
    table.add_column("Icon", justify="center", width=3)
    table.add_column("Track")

    status_style = {"✅": "green", "❌": "red", "🎸": "blue", "⏭️": "", "🚫": ""}
    for icon, stem in tracks:
        style = status_style.get(icon, "")
        table.add_row(icon, f"[{style}]{stem}[/{style}]" if style else stem)

    console.print(table)
    console.print()

def browse_directory(start_path):
    """Interactive terminal directory browser. Returns selected Path or None."""
    current_dir = [Path(start_path)]
    selected_index = [0]
    scroll_offset = [0]
    result = [None]
    filter_mode = [False]
    filter_text = [""]

    HEADER_ROWS = 3  # current path + blank line
    FOOTER_ROWS = 2  # blank line + hint bar

    def visible_rows():
        return max(5, shutil.get_terminal_size().lines - HEADER_ROWS - FOOTER_ROWS)

    def get_all_subdirs():
        try:
            return sorted(
                [p for p in current_dir[0].iterdir() if p.is_dir()],
                key=lambda p: p.name.lower(),
            )
        except PermissionError:
            return []

    def get_entries():
        entries = []
        if not filter_mode[0] and current_dir[0].parent != current_dir[0]:
            entries.append(("..", current_dir[0].parent))
        for p in get_all_subdirs():
            if not filter_mode[0] or filter_text[0].lower() in p.name.lower():
                entries.append((p.name, p))
        return entries

    def clamp_scroll(entries, rows):
        n = len(entries)
        if selected_index[0] < scroll_offset[0]:
            scroll_offset[0] = selected_index[0]
        elif selected_index[0] >= scroll_offset[0] + rows:
            scroll_offset[0] = selected_index[0] - rows + 1
        scroll_offset[0] = max(0, min(scroll_offset[0], max(0, n - rows)))

    def render():
        entries = get_entries()
        rows = visible_rows()
        clamp_scroll(entries, rows)
        n = len(entries)
        lines = [("class:header", f" {current_dir[0]}\n\n")]
        visible = entries[scroll_offset[0]:scroll_offset[0] + rows]
        for i_rel, (label, _) in enumerate(visible):
            i_abs = i_rel + scroll_offset[0]
            if label == "..":
                display = "  ..  (go up)"
            else:
                display = f"  {label}/"
            prefix = " > " if i_abs == selected_index[0] else "   "
            style = "class:selected" if i_abs == selected_index[0] else ""
            lines.append((style, f"{prefix}{display}\n"))
        if n > rows:
            pos = f"[{selected_index[0] + 1}/{n}]  "
        else:
            pos = ""
        if filter_mode[0]:
            lines.append(("class:footer", f"\n  /{filter_text[0]}  (↑↓ Move    Enter Select    Esc Cancel)"))
        else:
            lines.append(("class:footer", f"\n  {pos}↑↓←→ Move    Enter Select    / Filter    q Quit"))
        return lines

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        if selected_index[0] > 0:
            selected_index[0] -= 1
        app.invalidate()

    @kb.add("down")
    def _(event):
        if selected_index[0] < len(get_entries()) - 1:
            selected_index[0] += 1
        app.invalidate()

    @kb.add("pageup")
    def _(event):
        selected_index[0] = max(0, selected_index[0] - visible_rows())
        app.invalidate()

    @kb.add("pagedown")
    def _(event):
        selected_index[0] = min(len(get_entries()) - 1, selected_index[0] + visible_rows())
        app.invalidate()

    @kb.add("enter")
    def _(event):
        entries = get_entries()
        if not entries:
            return
        _, path = entries[selected_index[0]]
        result[0] = path
        app.exit()

    @kb.add("right", filter=Condition(lambda: not filter_mode[0]))
    def _(event):
        entries = get_entries()
        if not entries:
            return
        label, path = entries[selected_index[0]]
        if label != "..":
            current_dir[0] = path
            selected_index[0] = 0
            scroll_offset[0] = 0
            filter_mode[0] = False
            filter_text[0] = ""
            app.invalidate()

    @kb.add("left", filter=Condition(lambda: not filter_mode[0]))
    def _(event):
        if current_dir[0].parent != current_dir[0]:
            current_dir[0] = current_dir[0].parent
            selected_index[0] = 0
            scroll_offset[0] = 0
            filter_mode[0] = False
            filter_text[0] = ""
            app.invalidate()

    @kb.add("/", filter=Condition(lambda: not filter_mode[0]))
    def _(event):
        filter_mode[0] = True
        filter_text[0] = ""
        selected_index[0] = 0
        scroll_offset[0] = 0
        app.invalidate()

    @kb.add("escape", filter=Condition(lambda: filter_mode[0]))
    def _(event):
        filter_mode[0] = False
        filter_text[0] = ""
        selected_index[0] = 0
        scroll_offset[0] = 0
        app.invalidate()

    @kb.add("backspace", filter=Condition(lambda: filter_mode[0]))
    def _(event):
        if filter_text[0]:
            filter_text[0] = filter_text[0][:-1]
            selected_index[0] = 0
            scroll_offset[0] = 0
        app.invalidate()

    @kb.add("q", filter=Condition(lambda: not filter_mode[0]))
    @kb.add("c-c")
    def _(event):
        app.exit()

    @kb.add("<any>")
    def _(event):
        if filter_mode[0]:
            key = event.key_sequence[0].key
            if len(key) == 1 and key.isprintable():
                filter_text[0] += key
                selected_index[0] = 0
                scroll_offset[0] = 0
                app.invalidate()
        app.invalidate()

    control = FormattedTextControl(render, focusable=True)
    layout = Layout(Window(content=control))
    style = Style.from_dict({
        "header": "bold cyan",
        "selected": "bold white bg:#005faf",
        "footer": "dim",
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=True)
    app.run()
    return result[0]


if __name__ == "__main__":
    start = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    starting_path = browse_directory(start)

    if starting_path is None:
        console.print("[yellow]No directory selected.[/yellow]")
        sys.exit(0)

    get_lyrics_for_album(starting_path)

    for p in starting_path.iterdir():
        if p.is_dir():
            get_lyrics_for_album(p)