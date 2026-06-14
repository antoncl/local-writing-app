# TODO Ownership Invariants

This app keeps prose local-first and file-based. TODO ownership is split by
where the TODO belongs.

## Canonical Ownership

- `todo.yaml` owns project-level and scene/file-level TODO records.
- Scene Markdown owns embedded TODOs that are attached to prose selections.
- Embedded TODOs do not exist in `todo.yaml`.
- The TODO pane may show embedded TODOs, but those rows are derived from open
  editor panes and disappear when the owning scene is closed or the mark is
  removed.

Embedded TODOs are stored in scene Markdown as invisible comments:

```markdown
<!-- embedded-todo:id=todo_abc123;status=open;note=tighten%20image -->selected prose<!-- /embedded-todo -->
```

The editor renders that comment pair as a subtle TODO mark. The prose should
remain readable without visible tags.

## Runtime Invariants

- An embedded TODO ID may appear at most once in a scene.
- Deleting embedded prose deletes the embedded TODO because the scene markup is
  the canonical source.
- Completing or editing the note for an embedded TODO updates the scene markup.
- Copy/cut/paste of embedded TODO markup is scene-local editor behavior; no
  backend TODO record is created.
- Deleting a scene removes scene/file-level TODO records from `todo.yaml`, but
  embedded TODOs require no cleanup because they live in the deleted scene file.

## Validation And Repair

Project validation is read-only. It reports file structure and legacy TODO drift
caused by app bugs, direct file edits, or interrupted writes.

Project repair is explicit and mutating. For TODOs it may:

- remove file-level TODO records that point at missing scenes
- remove or normalize legacy anchored TODO records/comments from earlier
  prototypes

Embedded TODOs should be repaired by editing the scene Markdown because the scene
file is their canonical owner.
