# .mangaplay — Format Specification

**Status:** Stable
**Compatibility goal:** Any valid `.fountain` document is a valid `.mangaplay` document. Mangaplay-specific markers are invisible (or non-rendering) to Fountain parsers.

---

## 1. Introduction

### 1.1 Purpose

`.mangaplay` is a plain-text format for authoring manga, comics, and screenplays from a single source script. It extends [Fountain](https://fountain.io/) — the de facto open standard for plain-text screenplays — with first-class support for **pages** and **panels**, the structural primitives of manga and comics, which Fountain does not address.

### 1.2 Design Goals

1. **Fountain compatibility (one-way).** Any valid Fountain document parses cleanly as a `.mangaplay` document and produces an equivalent screenplay rendering.
2. **Plain text.** Writable in any editor, diffable in any VCS, readable without tooling.
3. **Page-first authoring.** Manga creators think in pages; the format makes pages explicit, not derived from layout.
4. **Panel-first composition.** Panels are the unit of visual composition; the format gives them dedicated syntax.
5. **No magic, no AI, no server.** The format is mechanically parseable. No external services required to render.

### 1.3 Non-Goals

- Replacing production tools (Photoshop, Celtx, Final Draft).
- Round-trip parity with Fountain when Mangaplay-specific markers are used. Fountain renderers gracefully ignore Mangaplay extensions; they do not reconstruct them.
- Pixel-perfect layout. The format describes *intent*; the renderer decides geometry.

### 1.4 Audience

This document is for tool authors implementing `.mangaplay` parsers and renderers, and for power users who want to understand the format directly.

---

## 2. Terminology

| Term | Definition |
|---|---|
| **Document** | A complete `.mangaplay` file. |
| **Title page** | The optional metadata block at the top of a document. Inherited from Fountain. |
| **Page** | A unit of layout. Authored explicitly with `# PAGE N`. |
| **Panel** | A bounded visual frame within a page. Authored with `Panel N` or `/* PANEL N */`. |
| **Tag** | A `[bracketed]` modifier attached to a panel that influences rendering (e.g. `[wide]`, `[silent]`). |
| **Scene heading** | Fountain-style location/time slug (`INT. KITCHEN - DAY`). |
| **Action** | Descriptive prose between dialogue blocks. |
| **Character cue** | Uppercase line introducing a speaker. |
| **Dialogue** | The line(s) following a character cue. |
| **Parenthetical** | A `(direction)` line between cue and dialogue. |
| **Transition** | A line ending in `TO:` (e.g. `CUT TO:`). |
| **Boneyard** | A `/* ... */` block. Stripped by Fountain renderers; meaningful to Mangaplay when the first token is `PANEL`. |
| **Note** | A `[[ ... ]]` inline annotation. Hidden or marginal in Fountain renderers. |

The key words **MUST**, **MUST NOT**, **SHOULD**, **MAY** are to be interpreted per [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

---

## 3. Document Structure

A `.mangaplay` document is composed of, in order:

1. An optional **title page**.
2. A sequence of **pages**, each containing **panels**, **scene headings**, **action**, **character cues**, **dialogue**, **parentheticals**, and **transitions**.

Parsing proceeds in two passes:

1. **Block pass** — identify page boundaries, panel boundaries, and Fountain block elements (scene heading, character cue, action, transition).
2. **Inline pass** — within each block, parse emphasis, notes, boneyards, and tags.

This mirrors the [CommonMark](https://spec.commonmark.org/) two-pass model.

---

## 4. Title Page

Identical to Fountain. A title page is a contiguous block of `Key: Value` lines at the start of the document, terminated by a blank line.

```mangaplay
Title: The Lighthouse
Credit: written by
Author: Pistol Taeja
Draft date: 2026-05-04
```

A `.mangaplay` parser **MAY** add a recommended key:

```mangaplay
Format: mangaplay
```

The format is presented as a single, current standard. No version suffix appears in the title page.

Multi-line values use 3+ space indentation on continuation lines, identical to Fountain:

```mangaplay
Author:
   Pistol Taeja
   with art by R. Singh
```

---

## 5. Pages

### 5.1 Syntax

A page begins with a line matching:

```
# PAGE <N>
```

- The line **MUST** start at column 0.
- `#` **MUST** be followed by exactly one space, then the literal word `PAGE`. Uppercase is canonical. Parsers **MUST** accept `Page` and `page` for tolerance, **SHOULD** emit a warning, and the formatter **MUST** always write `PAGE`.
- `<N>` **MUST** be a positive integer.
- Trailing content on the line **MAY** be present (e.g. `# PAGE 3 — climax`) and is treated as a label.

### 5.2 Examples

```mangaplay
# PAGE 1
# PAGE 2
# PAGE 17 — final splash
```

### 5.3 Behavior in Fountain Renderers

Fountain treats `#` lines as **section headers** — outline-only, non-rendered. A Fountain renderer will:

- Show `PAGE 1` in its outline view.
- Not insert a page break in the output.
- Not produce errors.

This means a `.mangaplay` document opened in a pure Fountain tool renders as a continuous screenplay with page labels visible only in the outline. **This is acceptable.** The compatibility guarantee runs Fountain → Mangaplay, not Mangaplay → Fountain with full fidelity.

If forced page breaks in Fountain output are required, an author **MAY** add `===` on its own line beneath the `# PAGE N` marker:

```mangaplay
# PAGE 2
===
```

Mangaplay parsers **MUST** treat the `===` line as redundant when it immediately follows a `# PAGE N` line.

### 5.4 Implicit Page 1

If a document contains panels or content before the first `# PAGE N`, that content **MUST** be assigned to Page 1 implicitly.

---

## 6. Panels

### 6.1 Inline Form

```
Panel <N> [tag] [tag] ...
```

- Mixed-case `Panel`, distinguishing it from `# PAGE` (uppercase).
- Tags follow the panel number, each enclosed in square brackets.
- The line **MUST** start at column 0.

This is the most readable authoring form and is what the formatter emits by default.

### 6.2 Boneyard Form (Fountain-Safe)

```
/* PANEL <N> [tag] [tag] ... */
```

- Wrapped in Fountain **boneyard** delimiters (`/* */`).
- `PANEL` **MUST** be uppercase to distinguish from prose.
- Tags are bracketed identifiers, space-separated.
- Both single-line and multi-line forms are supported (full Fountain boneyard semantics):

  ```mangaplay
  /* PANEL 3 [wide] [establishing] */
  ```

  ```mangaplay
  /* PANEL 3
     [wide] [establishing]
     [no-dialogue] */
  ```

- A boneyard whose first non-whitespace token is **not** `PANEL` is a regular Fountain author comment and **MUST** be stripped from rendered output.

The boneyard form is the Fountain-safe option: a strict Fountain parser will silently drop the panel marker, leaving only the screenplay content. Choose this form when round-tripping through Fountain tooling matters.

### 6.3 Behavior in Fountain Renderers

Boneyard blocks are **stripped entirely** by Fountain parsers. The screenplay output contains no trace of the panel marker. This is the cleanest compatibility outcome.

### 6.4 Tags

Tags are `[lowercase-kebab]` identifiers inside square brackets. They are advisory hints to the renderer.

Reserved core tags (non-exhaustive):

| Tag | Meaning |
|---|---|
| `[wide]` | Panel spans full page width |
| `[tall]` | Panel spans full page height |
| `[splash]` | Panel occupies entire page |
| `[silent]` | No dialogue or sound effects |
| `[establishing]` | Setting/location reveal |
| `[close-up]` | Tight framing |
| `[reaction]` | Character reaction shot |
| `[insert]` | Detail inset (object, text, etc.) |

Custom tags **MAY** be defined; renderers **MUST** ignore tags they do not recognize.

### 6.5 Implicit Panel 1

If a page contains content before its first panel marker, that content **MUST** be assigned to Panel 1 of that page implicitly.

---

## 7. Fountain Elements (Inherited Verbatim)

`.mangaplay` adopts Fountain's syntax for the following without modification. Implementations **MUST** follow [the Fountain syntax specification](https://fountain.io/syntax/).

### 7.1 Scene Headings

```mangaplay
INT. KITCHEN - NIGHT
EXT. CLIFFTOP - DAY
```

Forced scene heading: `.kitchen` (leading period).

### 7.2 Action

Plain prose paragraphs separated by blank lines. Action **MUST** be authored at column 0, identical to Fountain. Indented action is tolerated on read for compatibility but the formatter **MUST** emit column-0 action.

### 7.3 Character Cues and Dialogue

```mangaplay
ALICE
What was that noise?

BOB (O.S.)
(whispering)
Probably nothing.
```

Forced character cue: `@alice` (leading at-sign).

### 7.4 Parentheticals

```mangaplay
(whispering)
(to herself)
```

### 7.5 Transitions

```mangaplay
CUT TO:
FADE OUT.
```

### 7.6 Notes

```mangaplay
[[ remember to revise this ]]
```

Notes are visible-but-marginal in Fountain. Mangaplay treats them as author annotations and **SHOULD NOT** render them in the manga/comic output by default.

### 7.7 Boneyard

```mangaplay
/* this content is excluded from rendering */
```

In Mangaplay, boneyard is reserved for panel markers (Section 6.2) and **MAY** be used for author-only comments, identical to Fountain.

### 7.8 Forced Page Break

```mangaplay
===
```

Recognized for Fountain compatibility. **SHOULD NOT** be used as the primary page marker in Mangaplay documents (use `# PAGE N`).

### 7.9 Emphasis

`*italic*`, `**bold**`, `***bold italic***`, `_underline_` — per Fountain.

### 7.10 Centered Text and Lyrics

`> centered <`, `~lyric line` — per Fountain.

---

## 8. Compatibility Matrix

| Source | Target | Result |
|---|---|---|
| Valid Fountain | `.mangaplay` parser | **100% supported.** Renders as screenplay. No panels inferred. |
| `.mangaplay` (with `# PAGE N`, `/* PANEL */`) | Fountain renderer | Pages appear in outline only; panels stripped from output. Screenplay still renders correctly. |

---

## 9. Worked Example

```mangaplay
Title: The Lighthouse
Author: Pistol Taeja
Format: mangaplay

# PAGE 1

/* PANEL 1 [wide] [establishing] */

INT. LIGHTHOUSE - NIGHT

Wind howls. Rain lashes the windows.

/* PANEL 2 [close-up] */

ALICE
(whispering)
Did you hear that?

BOB
Hear what?

/* PANEL 3 [reaction] [silent] */

# PAGE 2

/* PANEL 1 [splash] */

The lighthouse beam sweeps across a dark sea.

CUT TO:
```

**Mangaplay rendering:** 2 pages. Page 1 has 3 panels (wide establishing exterior, close-up dialogue, silent reaction). Page 2 is a single splash panel.

**Fountain rendering:** A continuous screenplay with title page, scene heading, action, dialogue, transition. `PAGE 1` and `PAGE 2` appear in the outline. Boneyard panel markers are stripped.

---

## 10. Reserved for Future Use

- `## Chapter <N>` — chapter-level grouping above pages.
- `# SCENE <N>` — explicit scene grouping if needed.
- Per-panel character placement directives.
- Inline raster/asset references.

Implementations **MUST** ignore unknown `# UPPERCASE N` markers and unknown boneyard contents rather than erroring.

---

## 11. Versioning

This spec uses [semantic versioning](https://semver.org/). Future revisions follow it: breaking changes increment the major version, additive changes increment the minor version, editorial fixes increment the patch version. The current release is tracked in [CHANGELOG.md](CHANGELOG.md).

---

## 12. References

- [Fountain syntax — fountain.io/syntax](https://fountain.io/syntax/)
- [Fountain — fountain.io](https://fountain.io/)
- [Fountain (markup language) — Wikipedia](https://en.wikipedia.org/wiki/Fountain_(markup_language))
- [CommonMark Spec](https://spec.commonmark.org/)
- [CommonMark spec source — github.com/commonmark/commonmark-spec](https://github.com/commonmark/commonmark-spec)
- [RFC 2119 — Key words for use in RFCs](https://www.rfc-editor.org/rfc/rfc2119)
- [Writing a File Format Specification — fileformat.info](https://www.fileformat.info/mirror/egff/ch08_08.htm)

---

## Appendix A — Spec Document Conventions

This spec adopts conventions from CommonMark, Fountain, and the *Encyclopedia of Graphics File Formats* guidance:

- **Numbered top-level sections** for stable cross-reference.
- **Terminology section up front** — every term used in the spec is defined once, then referenced.
- **RFC 2119 keywords** (MUST/SHOULD/MAY) for normative requirements.
- **Worked example** at the end — readers learn faster from a complete sample than from prose.
- **Compatibility matrix** — explicit table beats prose for "what works with what."
- **Reserved-for-future-use section** — signals which extensions to expect, prevents accidental collisions.
- **Versioning section** — establishes how the spec itself evolves.
- **Conformance test corpus** — a spec without tests is a wish list; a spec with a test corpus is a standard.
- **External references at the bottom** — sources and related specs.

The doc is written so a tool author can implement a parser without reading the source of any existing Mangaplay codebase.
