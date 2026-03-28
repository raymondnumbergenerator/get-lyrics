import os
import sys
import zhconv
from pathlib import Path
from tinytag import TinyTag
from syncedlyrics import search

from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3

import re
from rich.console import Console
from rich.table import Table
from rich import box

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
    console.print(f"  [green]✅ Lyrics saved to[/green] [dim]{save_path.name}[/dim]")
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
    console.rule(f"[bold cyan]💿  {album_name}[/bold cyan]")
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
    table = Table(title=f"[bold]Summary — {album_name}[/bold]", box=box.ROUNDED, show_header=False, padding=(0, 1))
    table.add_column("Icon", justify="center", width=3)
    table.add_column("Track")

    status_style = {"✅": "green", "❌": "red", "🎸": "blue", "⏭️": "", "🚫": ""}
    for icon, stem in tracks:
        style = status_style.get(icon, "")
        table.add_row(icon, f"[{style}]{stem}[/{style}]" if style else stem)

    console.print(table)
    console.print()

if __name__ == "__main__":
    starting_path = Path(sys.argv[1])
    get_lyrics_for_album(starting_path)

    for p in starting_path.iterdir():
        if p.is_dir():
            get_lyrics_for_album(p)