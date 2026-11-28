# PDF Image Editor User Manual

Split, move and replace images inside a PDF, keeping the original text layer.

---

## 1. What it solves

Scanned documents and mixed text/image PDFs often need a large image cut apart, a middle piece punched out, or a watermark covered. General-purpose PDF editors make you either rasterise the whole page — losing the text layer — or fiddle around in Illustrator.

This tool splits every page into a **background** plus **independent image objects**:

- the **background** keeps the document's text, vectors and annotations and is rendered on demand at the target DPI;
- **image objects** can be dragged, scaled, split, trimmed, deleted and replaced individually.

Saving only swaps the images; everything else is left untouched.

## 2. Feature overview

**View**

- Pages are rendered at a DPI chosen from the current zoom, so zooming in stays sharp
- Wheel to scroll, `Ctrl`+wheel to zoom around the pointer, `Space`+drag or middle-drag to pan
- Light and dark themes; the system preference seeds the default once, then you switch by hand
- Page-margin guides, any number of them per edge, plus configurable snap lines for moving and resizing elements

**Edit**

- Drag, scale from any corner with the ratio locked (`Alt` for free ratio), stretch a single edge
- Multi-select (`Shift` to add, same page only): a group frame wraps the small boxes, drag it to scale them together
- Merge a multi-selection into one image: the highest-resolution member sets the pixel density, layers are composited in order, and transparent areas are flattened onto white — the result is opaque
- Drag a selection box over empty space to select everything it touches
- Drag across pages: drop an image on another page and it belongs to that page
- Split: drop a few cut lines on an image, then "Keep this cell / Extract this cell / Split into cells"
- Bring to front / send to back, delete, arrow-key nudging
- Paste an image from the clipboard (`Ctrl+V`)
- Edit an image in the system default program and send it back
- **Text boxes**: font, size, line height and color, with several fonts mixed inside one box
- **Highlighter**: horizontal bands that multiply over the page, so text underneath stays readable

**Save**

- Only the images are replaced; text, vectors, annotations, bookmarks and links all survive
- Writes a temporary file first, then swaps it in; an in-place save copies the previous version into `backup\` inside the data folder
- Export selected pages as a new PDF
- Black & white preprocessing: save a de-grayed copy, leaving the original alone

## 3. Installation

Requirements:

- Windows 10 1803 or newer (or Windows 11)
- **WebView2 Runtime** on the system (bundled with Windows 11 and most Windows 10 installs; otherwise install it once from Microsoft)
- [uv](https://docs.astral.sh/uv/)

```bat
setup.bat
```

It checks for `uv`, then creates `.venv` and installs the dependencies. Re-run it to upgrade dependencies or to move to another machine; versions are pinned by `uv.lock`.

The package index is fixed in `uv.toml` at the project root and defaults to the Aliyun mirror (`https://mirrors.aliyun.com/pypi/simple`); `uv.lock` records the same mirror URLs, and both are committed with the repo. To switch back to the official index, point `url` at `https://pypi.org/simple` and run `uv lock` again.

## 4. Starting

```bat
main.bat
```

It launches through `pythonw.exe`, so no console window appears. You can call it from any directory: at startup the working directory is pinned to the program folder, and every internal path is derived from the program directory and the system folders rather than from wherever you launched it.

On the **first run** you pick the interface language (the Windows UI language by default, English when there is no matching locale; pick another option and the dialog switches at once), then read the manual. Both steps must be finished with the button — Esc and clicking outside do nothing. This is the only entry point, so there is no "wrong program" case.

## 5. Interface

The window has five parts: the top bar, the tool rail on the left, the canvas, the inspector on the right, and the split bar at the bottom of the canvas (only in split mode). Each is described below.

**Top bar**

| Area | Contents |
|---|---|
| Left | Open, More (Save / Save As / Close current PDF); file name and the unsaved dot |
| Middle | Undo / redo, zoom (`−` / percentage field / `+` / Fit Width / 100%) |
| Right | Preprocess, Export Pages, Reload, theme toggle, Settings, show/hide inspector |

**Tool rail**

Always there, cannot be closed. Three icons decide what a press on the page does:

| Icon | Mode | A press on the page |
|---|---|---|
| Arrow | Select | Select, drag, use handles, marquee (the default) |
| T | Text | Drop a text box and start editing |
| Marker | Highlighter | Drag horizontally to lay down a band |

**Canvas**

Pages are stacked vertically, and only four of them are rendered: the current page, the one after it, the one before it, and the page after that. Pages rendered earlier stay in place when you move away — nothing is unloaded — but distant pages are never rendered ahead of time. A floating "current page / total" chip sits in the bottom-left corner of the canvas and the same line appears at the bottom of the inspector; the busy bar on the right of the top bar shows progress for long tasks such as opening and preprocessing.

**Inspector**

- Nothing selected: a hint plus a "Paste image" button
- One image selected: thumbnail, page, position (pt), size (pt), and "Split / Bring to front / Send to back / Edit externally / Delete"
- A text box or a highlight selected: page, position, size, and "Delete"
- Several selected: a hint plus "Delete"; a group frame appears on the canvas for scaling them together

**Split bar**

Appears at the bottom of the canvas once split mode starts. It shows how many horizontal and vertical cuts are placed and holds the four action buttons (keep / extract / erase / split into cells). The `kbd` hints on those buttons follow your custom key bindings.

## 6. Opening and viewing

### Open

Click "Open" or press `Ctrl+O`. The file dialog starts in `pdfs/` under the data directory and creates that folder if it is missing — keeping frequently used PDFs there saves a few clicks. Settings has a **Default folder for opening files** option; leave it empty to fall back to `pdfs/`.

You can also **drop a PDF onto the window**: with nothing open it simply opens; with a file already open and unsaved edits, you are asked whether to save, discard or cancel first. Dropping something that is not a PDF is rejected with a hint, and dropping several files opens the first one.

If opening fails you get a reason (corrupt file, encrypted, bad page count); the full stack trace goes to the log.

### Zoom

| Action | Effect |
|---|---|
| `Ctrl` + wheel | Zoom around the pointer |
| `Ctrl+=` / `Ctrl+-` | Zoom in / out (20% per step) |
| `Ctrl+0` | Fit width |
| `Ctrl+1` | Back to 100% |
| Percentage field in the top bar | Type a number and press Enter to jump to that ratio |

The zoom range is 10%–800%. Zooming only changes the on-screen page size; bitmaps are fetched in **steps**, so a new image is requested only when the ratio crosses a step boundary — continuous zooming in between does not re-transfer anything.

### Pan

Hold `Space` and drag, or drag with the middle mouse button. Release `Space` to return to selection mode.

### Page navigation

The inspector footer has a page field: type a number and press Enter or click "Go". Only integers between 1 and the page count are accepted.

Jumping is instant rather than a smooth scroll: in a 50-page document, going from page 1 to page 30 loads only pages 30, 31, 29 and 32 — the 28 pages in between are never rendered.

## 7. Editing images

### Selecting

- Click an image to select it; `Shift`+click adds or removes it
- **Multiple selection works within one page**: shift-clicking an image on another page replaces the selection with that image and says so
- Drag a box over empty space to select every image it touches — any overlap counts
- Click empty space without dragging to clear the selection
- `Ctrl+A` selects every image on the **current page** (Select tool only); `Esc` clears the selection (Select tool only)

### Moving

Drag the selection. A move only counts after 3px of travel, so a plain click never nudges anything. With several selected, dragging any one of them moves the whole group.

When **exactly one image** is selected it may be dragged outside the page (useful for bleed or layout work) and stays there on release; a multi-selection and text boxes are still kept inside the page. The part outside the page is clipped when printing/exporting, but its position is kept in the file.

### Scaling

With one image selected there are eight handles: four corners plus the midpoint of each edge.

| Handle | Behaviour |
|---|---|
| Corners | **Ratio locked** by default; hold `Alt` for a free ratio |
| Edges | Stretch one axis only, so the aspect ratio changes |

The edge handles exist for images whose displayed ratio differs from their pixel ratio: a square icon stretched flat can be squeezed back by dragging the top or bottom edge, no re-cropping needed. The pixels are untouched; only the rectangle on the page changes.

While scaling, the edge you drag (both edges, for a corner) **stops at the page border**: drag past it and the edge sticks there, so the image is never squashed or cropped. The exception is a **single selected image**, whose edges may be dragged outside the page.

While dragging an edge or corner, the moving edges snap to the reference and alignment guides and a green line appears. For ratio-locked corner scaling only the nearer edge snaps; the other edge follows the original ratio, so snapping never distorts the image.

The eight handles can be switched off in Settings, leaving the four corners.

The minimum size is 4pt — anything smaller is refused, because the rectangle would flip inside out.

Ratio-locked scaling is **driven by the long edge**: for a wide image only horizontal movement counts, for a tall image only vertical movement. That keeps the drag glued to the pointer instead of "drag down 1px, width jumps 10px".

### Multiple selection and the group frame

With two or more images selected, each keeps its own small outline and a group frame appears around them all:

- the small outlines have **no handles**; scaling is done from the group frame;
- the group frame has eight handles too: corners scale the group proportionally, edges stretch one axis;
- every image scales by the same factor, so relative positions and gaps scale with them;
- the smallest image never drops below 4pt, and the group cannot be dragged outside the page;
- dragging any image in the group moves the whole group.

### Trimming white borders

Select one or more images and press `G` (or use **Trim white borders** in the inspector). The program walks in from all four sides until every removed strip is light enough; what remains is the bounding box of all darker pixels, so the removed area is as large as possible. The content stays at the same place on the page — only the rectangle and the pixels shrink. One `Ctrl+Z` undoes the whole operation.

The inspector footer, above the page jump, also has a **White threshold** slider — the same value as the one in Settings; the next `G` uses it.

- Pixels are converted to BT.601 grayscale and **anything at or above the threshold counts as white**; the default is 227, the same value preprocessing uses to discard background grey, and it can be adjusted in Settings from 64 (about 1/4 gray) to 255 (pure white). The three channels no longer have to be exactly 255. Transparent and semi-transparent pixels are composited over white first;
- at the default, a 227 scanned background is trimmed while 226 light grey is still content; raising the threshold trims more aggressively, lowering it keeps more pale edges;
- an all-light image, or one with no light border, is left untouched and the status bar says so;
- a mixed selection containing text boxes or highlights is refused.

### Merging images

Select two or more images on the same page and the inspector shows **Merge images**. The selected images become **one**, the small boxes and the group frame disappear, and the selection lands on the result.

Merging flattens only the selected image objects into one bitmap; text, vectors and images outside the selection are untouched. Gaps inside the selection become white and may cover what is underneath.

| Rule | Detail |
|---|---|
| Extent | The result covers the union of the selected rectangles; gaps between images are filled with solid white |
| Resolution | Set by the **highest-resolution** member: pixel density = image pixel width ÷ displayed width in pt. The densest image has the smallest pixel footprint on the page |
| Scaling | Every other image is enlarged to that density with **bicubic** interpolation. In normal use this only ever scales up |
| Stacking | Composited bottom-to-top in z order, so upper images cover lower ones — exactly what the canvas shows |
| Result layer | Takes the **highest z** among the selected images. Merging collapses several layers into one; an unselected image that sat between them can no longer keep its old relative position |
| Transparency | A **solid white** base is laid down first, then images are composited over it by alpha; semi-transparent images blend normally, while gaps and transparent pixels show white. The result has **no alpha channel** and looks the same over any background |
| Undo | One entry; `Ctrl+Z` restores everything at once |

The result is an **opaque rectangular bitmap**: gaps and transparent pixels inside the union are solid white and will cover whatever is underneath.

Limit: a merge is capped at 40 megapixels and 12,000 px per side. Beyond that it is scaled down proportionally and the status bar says so.

**Images only**: if the selection contains a text box or a highlight, the button is not shown; the backend refuses too, since overlays have no resolution and should not be baked into a bitmap.

### Nudging

| Key | Distance |
|---|---|
| Arrow keys | 1pt |
| `Shift` + arrow keys | 10pt |
| `Ctrl` + arrow keys | 0.2pt |

Arrow-key nudging is not part of the configurable key map, so it never collides with global shortcuts.

### Across pages

Drop an image on another page and it moves there; the page number updates with it. If the target page has never been opened, the backend first pulls that page's existing images into the model — otherwise the model and the file would disagree when saving.

### Stacking

`Ctrl+U` brings to front, `Ctrl+L` sends to back. Both only affect the stacking order within one page.

### Deleting

Select and press `Delete`. The image disappears from the canvas, but the place it occupied in the original PDF is recorded in a tombstone table and erased on save — otherwise it would come back after saving.

### Pasting

`Ctrl+V` pastes the clipboard image onto the current page, centred and 40% of the page width. PNG / JPEG copied from a browser is passed through as-is; DIB data from a screenshot tool is parsed by hand.

### External editing

Select one image and press `Ctrl+Shift+E`: the program writes it to a temporary folder and opens it in the system default program. Edit and save it there, close that program, then click Done here and the image comes back.

Only the pixel content is replaced; position and size stay as they were.

### Straightening table lines

Select a table image and click **Straighten table lines** in the inspector. The program finds the ruling lines, makes them exactly horizontal or vertical, and draws every line at a fixed 3 px.

- **At least 170 px (adjustable)**: anything shorter is never treated as a table line, so small strokes in handwriting are left alone. Settings → Image processing adjusts it between 20 and 340 px, and the inspector footer (above the page jump) has the same slider; smaller values pick up shorter cell dividers, larger values are more conservative.
- **No isolated lines**: an endpoint must land on a perpendicular line (a corner or a T-junction). Merely crossing another line in the middle does not count; a line with both ends free is discarded.
- **Long lines are accepted first**: borders spanning at least 75% of the image width/height seed the grid. Other segments are accepted only when **both ends land on an accepted line**, so long cell dividers are handled, while a long handwritten stroke that does not touch a line at both ends is ignored.
- **Fixed 3 px width**: the original width is not measured; a 2 px outer border and a 4 px inner line both become 3 px.
- **Pure black core**: lines are drawn in `(0,0,0)` on the pixel grid, so the scanned dark grey is gone.
- **Endpoints follow the junction type**: at a T-junction the stem stops at the crossbar's centreline (up to 9 px of overshoot still counts as the same junction), so it never pokes out past the crossbar; only at a corner does it reach the far pixel edge of the other line, filling the outer corner.
- **Lines only, never text**: erasing is limited to each line's own narrow band.

The result is a new image and can be undone with `Ctrl+Z`. If no table lines are found, the image is left untouched and a message says so.

**Not covered**: pages skewed by more than about 0.5°, perspective distortion, dashed or broken lines (they are not bridged), and three-line tables with only parallel horizontal rules — they have no corner or T-junction, so they are skipped as isolated lines. Vector ruling lines that are PDF drawings rather than pixels of the selected image are also out of scope.

### Undo / redo

`Ctrl+Z` / `Ctrl+Y`. The undo stack stores geometry and image ids only — no pixel copies — so it can go deep (100 by default, adjustable from 10 to 500 in Settings).

One continuous drag is one entry; structural changes such as splitting and pasting are also one entry, reverted as a whole.

## 8. Splitting

Select **one** image, press `E` or click "Split" in the inspector. With several images selected split mode refuses to start — a cut belongs to exactly one image, and the message says so. Text boxes and highlights have no cells, so pressing `E` with one of those selected does nothing at all.

1. **Place cuts**: click inside the image for a horizontal cut; hold `Shift` and click for a vertical one. The dashed preview turns as soon as `Shift` goes down or comes back up — no need to move the mouse first. Any number of cuts is allowed, positioned where you click.
2. **Read the cells**: the cell under the pointer is highlighted, which enables "Keep this cell / Extract this cell / Erase this cell" on the split bar.
3. **Apply**:
   - `1` keep this cell — discard everything else
   - `2` extract this cell — punch it out of the original (leaving a white hole) and turn the piece into its own image
   - `3` erase this cell — punch it out and throw the piece away
   - `R` split into cells — every cell becomes its own image
4. **Take it back**: `Ctrl+Z` undoes **the last cut** (in the order you placed them, horizontal or vertical), not the whole split session.
5. **Leave**: `Esc` or "Cancel" on the split bar. Applying any action exits automatically.

Global shortcuts are suspended in split mode, so the two key maps can bind the same key without fighting.

> "Extract", "Erase" and "Keep": extract **punches a hole** and keeps the punched-out piece as a new image; erase punches the same hole but discards the piece; keep **replaces** — the original is gone and only that cell remains.

## 9. Text boxes

Switch the left rail to Text (the T icon) and click on the page: a text box lands with its **top-left corner at the click point**.

Settings can hold a **default text for new text boxes**: every new box is prefilled with it. **Hold `Ctrl` while clicking empty space** to create an empty box instead.

### Editing

- **Click** to select (and drag); **double-click** to edit — the caret is already in the box, and the left rail switches to the Text tool automatically.
- `Enter` starts a new line; `Ctrl+Enter` ends editing right away. With the caret on the trailing empty line, `Backspace` removes that line.
- `Esc` ends editing, **switches to the Select tool and selects the box** — it is ready to drag or nudge with the arrow keys, no extra click needed.
- **Clicking outside** ends editing and deselects the box; it does not create a new text box in the empty space.
- While editing, the box grows or shrinks with its content; a trailing Enter also counts as a line, and that empty line is visible while editing, matching the saved height.
- Pasting (`Ctrl+V`) or dropping text keeps **plain text only**: fonts, sizes, colours, bold, indentation and block structure from the source are dropped; line breaks are kept.
- Wrapping matches the saved result: Chinese breaks per character, closing punctuation (`, . ; : ! ?` and their fullwidth forms) never starts a line, opening punctuation (`( [ { «` and their fullwidth forms) never ends one; English breaks per word, overlong words are split.
- Empty the box and click away and it is deleted — no invisible leftovers.
- Leave the box at the **default text** and it is deleted too: an unreplaced placeholder is not content.
- The size is always an integer (px); use `−` / `+` on the toolbar or type it in.
- **Line height** is a multiple of the font size: 1.15 by default, adjustable between 0.8 and 3.

### Toolbar

The toolbar is pinned to the top-left of the box and appears as soon as it is selected:

| Control | Meaning |
|---|---|
| Font | Microsoft YaHei / SimSun / FangSong / KaiTi / SimHei / Times New Roman |
| Size | 6–200 px, 14 by default (the same size Edge uses for its annotations) |
| Line height | 0.8–3×, 1.15 by default |
| Color | Blue (default) / red / green / black; the first three come from Edge's annotation palette |

**Mixed fonts are allowed**: select part of the text and pick a font — only that run changes. One box can hold a SimSun paragraph followed by a FangSong one. The font name on the toolbar follows the run under the caret instead of sticking to the first run.

**Font changes follow glyph coverage**: select all and pick Times New Roman and only characters Times actually has glyphs for (Latin, digits, common symbols) switch; Chinese characters, fullwidth punctuation and anything else without a glyph keep their previous font instead of being silently replaced by a fallback.

### Width

A text box has **two handles, left and right**, and they change the width only — the text is re-wrapped, never scaled. The height always follows the number of lines and cannot be dragged. The default width is 4.5 cm and can be changed in Settings.

If the content is taller than the page, the box keeps extending downward instead of being clipped; dragging only clamps the top-left corner, so the bottom may overflow.

### The "current default"

Which style a new text box gets depends on the last text box you edited:

- Before you have edited any box, the defaults from Settings apply (Microsoft YaHei / 14 px / blue / line height 1.15 / width 4.5 cm);
- Once you have edited a box, the next new box inherits its style — the same behaviour as Edge.

This rule never shows up in the UI: it is "the set you used last", not another setting. It resets when you open a new document.

### On disk

Text boxes are saved as **real text** — not images, not PDF annotations:

- Edge, Chrome and Acrobat display, select, search and copy them, and printing keeps them;
- Fonts are **subsetted** before being embedded, so only the glyphs you used travel with the file — embedding all six fonts whole is 41 MB, a subsetted page of text is tens of KB;
- The fonts of the original document are not touched at all.

The program leaves a marker on the first line of its own content stream, so reopening the file still recognises "this box was made here" and keeps it editable. Text that came with the PDF has no such marker and stays baked into the background, exactly as before.

The **background image** in the editor never contains these boxes — the UI draws them separately, so moving one leaves no ghost behind. Printing, exporting and opening the file in another reader still show the text on the page.

## 10. Highlighter

Switch the left rail to Highlighter (the marker icon). The cursor turns into a dashed vertical rectangle; press and **drag horizontally** to lay down a band.

- Horizontal only — no freehand strokes;
- The band is created on release; while dragging you only see a preview, and a drag shorter than 4 pt is discarded;
- Always yellow `#FFF066`, matching Edge; 15 px tall by default, and the height is configurable in Settings (integer px);
- Yellow is the only colour — there is no colour palette.

### It multiplies, it does not cover

The band is drawn with **multiply** (PDF `/BM /Multiply`):

| Backdrop | Result |
|---|---|
| White paper | Bright yellow |
| Grey shading | Darker yellow |
| Pure black | Still black — no visible change |

That is exactly what a highlighter should do: text and lines are not covered, only tinted.

A band can be **selected and moved, nothing else**: no handles, no resizing. Like text boxes it can be selected and moved together with images; scaling a group only moves it, never resizes it.

## 11. Saving and exporting

### In-place save

`Ctrl+S`. An in-place save first copies the previous version into `backup\` inside the **data folder**, named `YYYYMMDD-<name>.bak.pdf`. **Every save is backed up**: when the name is already taken, the next one becomes `YYYYMMDD-<name>.bak1.pdf`, then `bak2.pdf`, and so on — the state before each save is kept, nothing is dropped. Backups stay out of the source folder so a PDF that gets delivered or archived never drags a `.bak.pdf` along.

Backups older than the retention period (30 days by default, adjustable in Settings) are deleted at the next start. PDFs inside the backup folder cannot be opened: they are snapshots taken before a save, and editing one would only edit a copy.

While saving, the status bar at the bottom of the window (the same one every other message uses) holds "Saving — don't edit the document right now", and the canvas plus shortcuts are locked; it disappears when the write finishes. Large files take a few seconds, and clicks during that window are not treated as edits.

### Save As

`Ctrl+Shift+S`, default name `<name>-edited.pdf`. After saving, the new file becomes the baseline and further edits apply to it.

### Close current PDF

**Close current PDF** in the **More** menu of the top bar releases the current file and returns to the empty state (only "Open PDF" in the middle). With unsaved changes it asks "Save / Don't save / Cancel" first: saving writes the file before closing, while Don't save discards only the in-memory edits and leaves the file on disk untouched. Closing does not quit the program.

### What saving does

1. Remove the previous version of the text boxes and highlights this program drew;
2. Redact every image at its **original position** (`src_rect`) to remove it from the page content;
3. Re-insert every image at its **current position** (`rect`), stacked in z order;
4. Draw this page's text boxes and highlights again (this is where the fonts are subsetted);
5. Write a temporary file → reopen it to verify the page count → replace the target.

Text, vectors, annotations, bookmarks and links therefore survive; there is no "drop the text layer" option to choose.

Two details:

- **Annotations**: `apply_redactions` also deletes annotations that fall inside the rectangle, so saving detaches the page's `/Annots` first and reattaches it afterwards — not a byte of the annotation objects changes.
- **Rotated images**: `insert_image` can only place images in 90° steps, so non-axis-aligned images are not editable and stay in the background untouched.

When saving finishes you are told which path was written and how many images were replaced. A problem with one image does not abort the save; it is listed instead:

| Message | Meaning |
|---|---|
| An image on page N was clamped | The image extended past the page edge and was clipped on save |
| An image on page N was skipped | Zero size, nothing inserted |
| An image on page N failed to insert | Encoding or write error; the original is still in the background |
| Page N failed to erase | The redaction did not apply; the original may remain |
| Annotations on page N could not be restored | In rare cases writing `/Annots` back fails |
| Text boxes or highlights on page N could not be written | Drawing the overlay failed; the images were already handled, the text on that page was not saved |
| Saved, but the editor could not reopen the file | The file on disk is fine; click Reload in the top bar to continue |

### Export pages

`Ctrl+E`, enter page numbers (for example `1-3,5,7-9`; a full-width comma also works) and export them to a new PDF.

- Export reads the **file on disk**, so unsaved edits stop it — save first, then export;
- Out-of-range pages, backwards ranges and malformed tokens are skipped and listed afterwards, so pages never go missing silently.

### Reload

The ↻ button in the top bar re-reads the current file from disk and discards in-memory edits. Unsaved changes trigger a confirmation first.

## 12. Black & white preprocessing

Scans usually carry a layer of grey background that looks bad in print or archive. "Preprocess" in the top bar converts every image in the document to grayscale, pushes pixels brighter than a threshold to pure white, and **saves the result as a new file**.

The button opens an explanation first, and it offers two routes:

- **Process the open document**: use the file you are editing, no need to pick a source. It requires a clean document — preprocessing works on the on-disk version, so opening the result afterwards would drop your unsaved edits;
- **Process another file**: pick any PDF; it does not have to be open.

Then pick the target file; choosing the source file itself is refused.

| Item | Detail |
|---|---|
| What it processes | Raster images on the pages; text, vectors and annotations are left as they are |
| What it skips | Images with an alpha channel (logos, watermarks) — thresholding would turn transparent areas into black blocks |
| Threshold | 227 by default; change `preprocess_threshold` in `app.json` in the data folder (0–255) |
| Output | The target file you choose; choosing the source file itself is refused |
| Progress | The busy bar on the right of the top bar shows processed / total |

When it finishes you are told where the file went and how many images were processed, then asked whether to open the result right away. Run it again to redo the work — the source file is never modified.

> The higher the threshold, the more light grey becomes white; 227 suits most scans. Below 200 you start erasing pale lines and light colour along with the background.

## 13. Keyboard shortcuts

**Everything here can be rebound in Settings → Shortcuts**, effective immediately. Duplicate combinations inside one scope are rejected on the spot.

| Key | Action |
|---|---|
| `Ctrl+O` | Open |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As |
| `Ctrl+E` | Export pages |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+A` | Select all on the current page (Select tool only) |
| `Esc` | Clear the selection (Select tool only); while editing a text box, finish editing and select it |
| `Ctrl+V` | Paste image (plain text only when a text box is being edited) |
| `Ctrl+0` / `Ctrl+=` / `Ctrl+-` / `Ctrl+1` | Fit width / zoom in / zoom out / 100% |
| `Delete` | Delete selection |
| `Ctrl+U` / `Ctrl+L` | Bring to front / send to back |
| `Ctrl+Shift+E` | Edit the current image externally |
| `Ctrl+I` | Show / hide the inspector |
| `Ctrl+,` | Settings |
| `E` | Enter split mode (images only) |
| `G` | Trim white borders on the selected images |
| `Z` / `X` / `C` | Switch to Select / Text / Highlighter mode |
| Arrow keys (`Shift` faster, `Ctrl` finer) | Nudge position |
| `Space` + drag / middle-drag | Pan the canvas |

Switching tools clears the selection; `Ctrl+A` and `Esc` only work in the Select tool.

**Split mode has its own key map**; global shortcuts are suspended:

| Key | Action |
|---|---|
| `1` / `2` / `3` | Keep the cell under the pointer / extract it / erase it |
| `R` | Split into cells |
| `Ctrl+Z` | Undo the last cut |
| `Esc` | Leave split mode |

## 14. Settings

`Ctrl+,` or the gear in the top bar.

**There is no Save and no Cancel**: every change is written to `app.json` in the data folder immediately, and closing the dialog undoes nothing. The red "Reset all" at the bottom-left restores settings, shortcuts, guides and snap lines together.

Settings are grouped into blocks — General, Image processing, Text boxes, Highlighter, Logs, Backups, Shortcuts, About — separated by a thin grey rule.

| Item | Range | Notes |
|---|---|---|
| Language | 中文 / English | Applied immediately, window title and hints included; the list is sorted by language code |
| Theme | Light / Dark | No follow-system option; the system preference seeds it once on the first run. The moon/sun button in the top bar does the same |
| Default folder for opening files | Any folder | PDF dialogs start here; leave empty to use `pdfs/` under the data directory |
| Undo limit | 10–500 | Lowering it only affects entries pushed afterwards |
| Guides | On / Off | The page-margin lines on the canvas |
| Eight handles | On / Off | Off leaves only the four corner handles |
| Margins | 0–300 mm | Left / top / right / bottom; each edge takes several values separated by commas, e.g. `10, 50`. Stored as a sorted, de-duplicated list and formatted back to `10, 50` |
| Snap lines | 0–300 mm | Same four-edge, multi-value input. Defaults to the five guide positions plus 85 mm from the left; used for snapping while moving or resizing, hidden otherwise |
| Shortest table line | 20–340 px | 170 by default; drag the slider, and **Reset** next to it returns to 170. Shorter lines are not treated as table borders. The inspector footer has the same slider |
| Trim white threshold | 64–255 | 227 by default, matching the grey level preprocessing discards; drag the slider, and **Reset** next to it returns to 227. 64 is about 1/4 gray, 255 is pure white. The inspector footer has the same slider |
| Default font | Six families | Font for new text boxes |
| Default size | 6–200 px | 14 by default; integers only |
| Default color | Blue / red / green / black | Color for new text boxes, blue by default |
| Default width | 10–300 mm | 45 (4.5 cm) by default |
| Default line height | 0.8–3× | 1.15 by default; a multiple of the font size |
| Default text for new text boxes | Any text | Prefilled when creating; hold `Ctrl` while creating to start empty |
| Highlighter height | 4–200 px | 15 by default |
| Log level | Debug / Normal / Warnings / Errors | Takes effect at once and keeps writing to the same file |
| Clean up logs automatically | On / Off | Deletes log files older than the retention period at startup; turn it off to keep them all |
| Keep logs for (days) | 1–365 | 30 by default; has no effect while the switch above is off |
| Keep backups for (days) | 1–3650 | 30 by default; at startup, backups in `backup\` older than this are deleted |
| Shortcuts | Two scopes | Click a field then press the combination; "Reset shortcuts" restores keys only |

Shortcuts are normalised through `event.code`, so `Ctrl+Shift+S` and `Ctrl+S` never get confused by Shift changing the character, and the same bindings work on any keyboard layout.

The last block in Settings is "About":

| Item | Notes |
|---|---|
| Version | Current version, read from `pyproject.toml` |
| Data folder | Where settings and the default PDF folder live; defaults to `%PROGRAMDATA%\six-coin\pdf-image-editor`. An input box with "Change" and "Reset" on its right: pick a folder and `pdf-image-editor` is appended automatically; the old folder is copied there **after a restart** and then removed. Press "Restart now" under the field when you are done; unsaved changes are held back first |
| User manual | Opens the manual in the current language (English if that file is missing) |

## 15. Files and folders

The program folder holds code only; runtime files live in system folders.

```
program directory\
├─ main.bat / main.pyw   entry point
├─ setup.bat             environment setup
└─ app\                  all code

%PROGRAMDATA%\six-coin\pdf-image-editor\     data folder (configurable)
├─ app.json             settings (language, theme, guide margins, text/highlighter defaults, key bindings)
├─ backup\              pre-save backups, one per save, YYYYMMDD-<name>.bak.pdf
└─ pdfs\                default folder for the open dialog

%LOCALAPPDATA%\six-coin\pdf-image-editor\
├─ logs\                one log file per launch
├─ locks\               locks
└─ data-dir.txt         data folder pointer

%TEMP%\six-coin\pdf-image-editor\            scratch files for external editing; anything older than a day is cleaned on start
```

- Logs live in `%LOCALAPPDATA%\six-coin\pdf-image-editor\logs\`, named `main_*`, one file per launch, rotating at 5 MB. Only the last 30 days are kept by default; anything older is deleted at startup.
- Backups live in `backup\` inside the data folder, one per in-place save (numbered `bak1`, `bak2` when names repeat), kept for 30 days by default. They move with the data folder when you change it.
- `app.json` is written atomically (temporary file + replace), so a crash mid-write never leaves half a file. A hand-edited file that breaks is reported with its file name — it is never silently reset.
- Unknown keys in the configuration are preserved, which keeps old and new versions compatible.
- The data folder always ends with the project code: picking `D://Data` gives `D://Data//pdf-image-editor`. On a change the old contents are copied there after a restart: folders are merged, and files already present in the target are never overwritten. If the copy fails nothing is touched and Settings says why — you never end up with a new folder and no settings. The old folder is removed once the switch succeeds.

## 16. Troubleshooting

**Opening a PDF fails**
The file may be corrupt, have no usable pages, or not be a PDF at all. The log has the full stack trace; first check that another reader can open it.

**Saving fails, the file is in use**
The target PDF is open in another program (Acrobat and Edge tabs both hold a lock). Close it and save again. Read-only files are caught earlier with their own message.

**An image cannot be selected or dragged**
Two cases: the page is rotated, or the image is placed at an angle. `insert_image` can only insert in 90° steps, and forcing an edit would just produce a misaligned, oversized copy — so those images stay in the background and are preserved as they are. The inspector reports how many such images a page has.

**The original image is still there after saving**
Either it was never recognised as an editable object (same cases as above) or erasing failed. Check the list shown when saving finishes; it names the page and the reason.

**The big image came back after splitting**
It does not. Each page's images are read into the model only the first time that page is opened, so deleted or split-away images never reappear.

**The `.bak.pdf` is not next to the file any more**
Backups moved to `backup\` inside the data folder (Settings → About → Data folder). Names carry a date prefix, e.g. `20261123-report.bak.pdf`; repeated saves on the same day become `.bak1.pdf`, `.bak2.pdf`, each holding the file as it was right before that save.

**Preprocessing skipped an image**
That image has an alpha channel (logo, watermark); thresholding would turn its transparent areas into black blocks, so it is skipped. Such images are meant to stay as they are.

**Chinese in a text box looks different from the screen**
That run was written with a font that has no Chinese glyphs, such as Times New Roman (the default font when the box was created, or inherited from a paste), so the save falls back to another face. Switch that run to a Chinese font to fix it; if you changed the font to Times later, Chinese keeps its previous font and this does not happen.

**A shortcut does nothing**
First check whether you are in split mode (global shortcuts are suspended), then whether a save is running (the canvas and shortcuts are locked while saving), then whether an input has focus (keys go to the input). If you rebound keys, Settings marks the conflicts.

**The window is blank**
The WebView2 runtime is missing or too old. Install [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) once and start again.

**Changing the data folder had no effect after a restart**
Look at the line under the field in Settings: if it still says "Takes effect after restart", the copy has not succeeded yet (missing drive, file in use, no write permission). Type the current folder back or press "Reset" to cancel the change; once the problem is fixed press "Restart now" — closing the window and starting it again works too, but it must really exit: while the old process is alive, launching again only brings that window to the front instead of opening a second one.

## 17. Known limitations

- **Rotated pages are not editable**: on a page that has been rotated as a whole, none of its images can be edited.
- **Non-axis-aligned images are not editable**: rotated or flipped images stay in the background.
- **Rotation is limited to multiples of 90°**: a constraint of the insertion API, not a setting.
- **Splitting works on one image at a time**: entering split mode with several selected says only one image can be split.
- **Export requires saving first**: export reads the file on disk, not the in-memory edits.
- **Preprocessing only handles raster images**: vectors and text are not thresholded, so a grey background painted as vector art stays where it is.
- **Only four pages are preloaded**: distant pages render when you get near them, so dragging the scrollbar quickly shows grey placeholders for a moment.
- **No text boxes or highlights on rotated pages**: the page coordinate system no longer matches the canvas — the same reason rotated images are not editable.
- **Text does not re-wrap while you drag the width**: the box re-wraps on release, so the text looks clipped for a moment mid-drag.
- **Chinese written in Times New Roman from the start uses a system fallback font**: Times has no Chinese glyphs, so such mixed runs may differ by a character or two after saving; changing a run to Times later keeps the previous font for characters without a glyph. The five Chinese fonts (YaHei / SimSun / FangSong / KaiTi / SimHei) match the saved result line for line.
- **Text boxes and highlights are only editable where the marker is understood**: they are page content, so other readers show, select and print them, but they cannot be edited there like annotations.
- **Overlays always sit above images on the same page**: they do not take part in image z-order (bring to front / send to back apply to images only).
- **Merging flattens several layers into one**: the result takes the topmost selected layer; an unselected image that sat between the selected ones cannot keep its old relative position.
