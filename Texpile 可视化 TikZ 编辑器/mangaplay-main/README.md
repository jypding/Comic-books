# Mangaplay

Mangaplay is a plain-text markup format for writing manga, comics and screenplays. It extends the [Fountain Format](https://github.com/nyousefi/Fountain) with support for pages and panels, filling the gap for writers who want to do more than focus on the story alone.

A `.mangaplay` file is human-readable text. You can write in any editor, diff in any VCS, and share without special tooling. Mangaplay supports everything a comic, manga or webtoon writer needs in the early creative phase of the writing process.

Mangaplay is great for getting your story out of the gate, creating screenplays to share with the film/tv communities to get feedback on the story, and sharing clearly explained panels to communicate with artists.

For more details see [mangaplay.studio](http://mangaplay.studio).

## Example

Let's say you wanted to write a screenplay with a manga panel layout in mind — introduce the character on the right, then follow up panels to expand the story. You could write something like the following:

```mangaplay
# PAGE 1 INT. DARK OFFICE CUBICAL

Panel 1 [V][L]
The WORKER sits, head down, hand slapping at his keyboarding.

Panel 2
His fingers target each cap of the key.

Panel 3

Panel 4 [H]
A PHONE rings, the Worker grits his teeth.

    WORKER
    (frustrated)
    Can't they do anything right.

Panel 5 [GROUP]
Panel 6
```

The above script would be interpreted in the manga format as below:

    +------+------+
    |..P2..|......|
    +------+..P1..+
    |..P3..|.(L)..|
    +------+------+
    |.....P4......|
    +---+-----+---+
    |.P6|.....|.P5|
    +---+-----+---+

- `# PAGE N` marks a new page. Add an optional scene heading inline.
- `Panel N` marks a new panel. Tags like `[V]`, `[L]`, `[H]`, `[GROUP]` control layout.
- Character names in CAPS, dialogue indented beneath.

## Panel tags

| Tag | Effect |
|---|---|
| `[H]` | Wide panel, fills the row |
| `[V]` | Tall panel |
| `[SPREAD]` | Splash page, fills the entire page |
| `[GROUP]` | Opens a shared row with the panels after it |
| `[INSET]` | Small window inside the panel above |
| `[SPLIT]` | Draws a divider through the middle of the panel |
| `[BLEED]` | Faded border instead of solid |
| `[BORDERLESS]` | No border |
| `[S]` | Small size |
| `[L]` | Large size |

Tags stack: `Panel 1 [H] [BLEED] [L]`

## Screenplay export

Because Mangaplay extends Fountain, the same script exports as a standard screenplay. Pages and panels are stripped, leaving only the action, dialogue and scene headings.

```
INT. DARK OFFICE CUBICAL

The WORKER sits, head down, hand slapping at his keyboarding.

His fingers target each cap of the key.

A PHONE rings, the Worker grits his teeth.

    WORKER
    (frustrated)
    Can't they do anything right.
```

## Specification

See [syntax.md](syntax.md) for the full format specification. More sample scripts are in the [sample/](sample/) folder.

## License

All code is copyright Pistol Taeja. Released under an MIT license. Do whatever you want with this code, be nice if you passed on kind words as the person did for me.

See the included LICENSE file for legal jargon.

## Contact

If you have any questions, or just want to say 'hi', you can catch me on Twitter [@reallyskint](https://twitter.com/reallyskint).

## Credits

### Mangaplay Studio

The [Mangaplay Studio App](https://mangaplay.studio/app) and [Mangaplay For Google Docs](https://chromewebstore.google.com/detail/hiidpbendbgfcdidhccnldbkgdeikibi) was developed by Pistol Taeja to accompany the format while developing mangas in 2022.

### Fountain Format

Fountain comes from several sources. John August and Nima Yousefi developed Scrippets, which used simple markup to embed screenplay-formatted material in websites. Stu Maschwitz drafted a more extensive spec known as Screenplay Markdown or SPMD, designed for full-length screenplays.

Stu and John discovered that they were simultaneously working on similar text-based screenplay formats, and merged them into what you see here. Other contributors to the spec include Martin Vilcans, Brett Terpstra, Jonathan Poritsky, and Clinton Torres.
