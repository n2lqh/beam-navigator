# Compare my session with net control's list — design

Owner request, 2026-11-24 (item 15 of the 2026-11-23 Monday nets review).

## Intent

After a net, net control publishes the official check-in list. The owner wants to see
where it differs from what they logged, and add the stations net control had but they
didn't into their own session for that night, so attendance and "regulars not heard
yet" stay right at the next session.

## Goals

- On the Import page, when the picked net and date already have the owner's own session
  (active or closed), offer **Compare with my session** next to **Save**.
- Show the differences in three groups:
  - **Net control had, you didn't:** each row ticked, with **Add ticked stations**.
  - **You had, net control didn't:** shown only.
  - **On both lists:** shown only; a name or grid that differs is highlighted.
- Adding puts the ticked stations into that session.

## Non-goals and anti-goals

- Comparing never removes or changes anything already in the owner's log.
- Comparing never creates a second session for the same night (it would double the
  night in attendance counts).
- Nothing here moves a rotator.

## Approaches

1. Button on the live net screen. Not chosen.
2. **Import page offers Compare with my session (owner's choice).** One place for
   everything pasted from net control.

## Design

- **One session per net per night (owner, 2026-11-24):**
  - **Start session** on a net and date that already has the owner's session opens that
    session instead of creating another.
  - On the Import page, when the owner's session exists for that night, **Compare with
    my session** replaces **Save**, so the official list never becomes a second session.
  - Importing for a net and date that already has an imported list offers only
    **Replace** or **Cancel**, even when the text differs. **Keep both** is removed.
    The store refuses a second session for a night, so nothing else can create one.
  - The existing duplicates (DVFRC Friday 50 MHz, 2026-11-20: empty sessions #19 and
    #20 beside #21 with 8 check-ins) are removed only with the owner's approval. They
    are not an app feature.
- **Matching:** by base callsign, as the duplicate check does (`K1ABC/P` matches
  `K1ABC`). Only rows the review table includes count, using the owner's edits there.
- **Added check-ins:**
  - Name, grid and QTH start from the reviewed row. Then, as on the I-hear line, QRZ
    fills each blank and replaces a 4-character grid with its 6-character grid inside
    that square, even when net control gave no grid (owner, 2026-11-24). QRZ's grid
    counts only when QRZ's position came from the station or its address (decision 49).
    A stored QRZ answer is used first. Without a QRZ login, the saved record and the
    list's details are used.
  - The station record follows the import's rules, and the QRZ answer is kept as on any
    lookup.
  - Heard state is **Not heard**, and notes read "From net control's list".
  - Sequence numbers come after the owner's own. Log time stays blank because the real
    time is unknown.
- **Closed session:** Add still works, since this happens after the net. The session
  stays closed.
- **Raw text:** the pasted list is saved on the session. Any text already there is kept,
  and the new text is appended.
- **After adding:** "Added N stations" with an **Open live net** link.

## Left to the builder (my calls)

- Layout of the three groups, and the highlight style for differences.
- The repository method that adds to a closed session (an explicit, named path).
- A decision record (next free number) and a user-guide section.
