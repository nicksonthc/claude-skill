# Before / after screenshots

Read this from step 3 of `SKILL.md` when the diff changes what a page shows. It needs the Chrome browser tools (`claude-in-chrome`). A reviewer sees the change in one glance at a **pair**: the same surface, same data, same state, taken once at the base and once at HEAD.

## 1. Pick the surfaces

List every **surface** the diff changes: a page, a panel, a dialog, a form, an open dropdown. A component reused on three pages counts on each page it changes. Choose test data that exercises the change (a record that has the new field, a search that returns results), and the same record for both shots.

Done when each changed surface has a name, a URL and the clicks that reach the state to capture.

## 2. Capture after, then before

Use the project's own way of running the app (its run skill, `.dev-local/` scripts, `CLAUDE.md`), signed in with local test users, and the browser tool (`computer` → `zoom` on the changed region with `save_to_disk: true`). Save as `<n>-<surface>-after.png` / `-before.png` in the scratchpad.

- **After**: the app at HEAD, for every surface.
- **Before**: swap the base's frontend into the working tree so the running dev server hot-reloads it at the same origin, and the sign-in carries over. Do this only on a clean tree with everything committed:
  ```bash
  git checkout <base> -- <frontend dir>     # e.g. web/src
  # … capture every "before" …
  git checkout HEAD -- <frontend dir>       # restore
  git status --short                         # must be empty again
  ```
  A backend change the base frontend never calls is harmless. If the before state needs base backend behaviour, run a second instance on another port instead.
- Reach each state by reading and clicking only. Leave every form with Cancel, never Save, so the shots write nothing.
- Same viewport, same zoom region, same record for both shots of a pair. A surface the base did not have gets an after shot only.

Done when every surface has its pair (or a lone after shot for a new one), you have opened each image, and the change is visible by comparing the two.

## 3. Upload the images

The PR body needs URLs. Upload the images as GitHub **attachments** through the PR page in Chrome (the user's choice: nothing goes into the repo or any branch), then read back the `https://github.com/user-attachments/assets/<id>` links. **Uploading is posting**: it happens in step 5, after the user approves the draft. Until then, show the user the local file paths.

GitHub's comment box has no file input until its "add files" button is clicked, and that click opens a native picker the browser tool cannot drive. A localhost fetch from the page is blocked by GitHub's CSP. What works is to stage your own input and paste from it:

1. Open the PR (or any page with a comment box) in a new tab, and run this in the page:
   ```js
   const inp = Object.assign(document.createElement('input'), {type: 'file', id: 'cc-shots'});
   inp.setAttribute('aria-label', 'cc screenshot staging input');
   inp.addEventListener('change', () => {
     const ta = document.querySelector('textarea[placeholder="Leave a comment"]');
     for (const f of inp.files) {
       const dt = new DataTransfer(); dt.items.add(f); ta.focus();
       ta.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
     }
   });
   document.body.appendChild(inp);
   ```
2. `find` the staging input, then `file_upload` **one file per call**, waiting ~4 s each. Each paste appends an `<img … src="https://github.com/user-attachments/assets/…">` line to the textarea, in order. Read the textarea after each batch; the `width`×`height` on each line confirms which file it is.
3. Clear the textarea (the native value setter plus an `input` event) and remove `#cc-shots`. **Never submit the comment.** Close the tab.

The links render for anyone who can see the repo, private ones included.

## 4. The body section

Put it between Summary and Test plan, one row per surface, with the state in the first column:

```markdown
## Screenshots
| | Before | After |
|---|---|---|
| **<surface>**: <state> | ![before](<url>) | ![after](<url>) |
```

In step 4's draft, write the image cells as `<local path>`. Step 5 swaps in the URLs after the upload. In the table, `<img src="<url>" width="320" alt="…">` keeps tall shots from swamping it.
