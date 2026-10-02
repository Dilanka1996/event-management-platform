# Architecture Overview (in plain language)

## What this is

Imagine a system for running events — conferences, weddings, meet-ups. Each
event has sessions on a schedule, rooms, and people with different levels of
access. On top of that sits a **helper** you can talk to in plain English:
"Schedule a 45-minute design review next Tuesday at 9am in whichever room is
free." The helper figures out what you mean and does it for you.

## Assistant with no keys

Think of the AI helper as a **very capable personal assistant who has no
authority of their own**. They can read the schedule, make suggestions, and
draft changes but they **cannot act on their own**. Every time they want to
change something, they have to:

1. **Write down exactly what they plan to do** ("book Room A on Tuesday at 9am").
2. **Show it to you and wait for your "yes."**

Nothing happens without that approval. The assistant can be wrong, confused, or
even tricked by a strange instruction — and it still can't cause any damage,
because it was never given the keys.

## Why this matters

Most "AI helper" projects make the mistake of trusting the AI to behave. They
write careful instructions ("please don't do anything risky") and hope for the
best. That's like leaving your car keys in the ignition and taping a note to the
windshield that says *"please don't steal this car."*

This project does the opposite. The **safety rules live in the software, not in
the AI's instructions.** The AI only *understands* what you said; the actual
decisions and safety checks happen in ordinary, predictable software that the
AI cannot influence — no matter how cleverly it's asked.

## The three parts

```
  YOU ──── talk to ────▶  THE HELPER  ──── asks permission ────▶  YOU
   ▲                          │
   │                          ▼
   └──── see every step ◀──  THE PLATFORM (the real system)
                            who's allowed, what's scheduled
```

1. **You** — type a request in plain English, and approve or reject what the
   helper proposes.
2. **The helper (the AI)** — turns your words into a clear plan. It's smart about
   *understanding*, but it only ever *suggests*. It does nothing on its own.
3. **The platform (the real system)** — the actual event data and the rules about
   who can do what. This is where every real change happens, and where the final
   safety check lives.

## What keeps it safe and trustworthy

- **Nothing is written without your approval.** Reads are free; changes always
  ask first. Anything destructive asks twice.
- **You see exactly what will happen** before it happens — the real details, not
  a vague summary.
- **If something is denied, it's handled calmly** — no crash, no silent failure,
  no pretending it worked. The helper tells you plainly what didn't go through.
- **The final rulebook is outside the AI.** Even if the AI were fooled by a
  sneaky instruction hidden in the data, the real system would still refuse
  anything the person isn't allowed to do.
- **You can follow along.** Every step the helper takes is shown, so you can
  reconstruct exactly what happened and why.

## An example, start to finish

You type: *"Schedule a 45-minute design review next Tuesday at 9am in whichever
room is free."*

1. The helper works out *which event*, *what exact date and time* (in the
   event's own time zone), and *which room is actually free* — by looking, not
   guessing.
2. It shows you: *"Book Room A, Tuesday 9am–9:45am. Approve?"*
3. You say yes. **Only now** is the booking made.
4. If you'd said no, nothing would have changed — and the helper would simply
   tell you it was cancelled.

If no room were free, it would **ask you** instead of silently booking something
wrong.
