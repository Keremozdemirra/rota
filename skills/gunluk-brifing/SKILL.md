---
name: gunluk-brifing
description: Günün tek sayfalık brifingini hazırlar — bekleyen e-postalar, taahhütler, bugün yapılması gerekenler ve dikkat isteyen tek şey. "Günlük brifing", "günü özetle", "bugün ne var", "beni bilgilendir", "neyi kaçırıyorum" dendiğinde kullan.
---

# Daily briefing

## Purpose
Produce one page Kerem can read in two minutes in the morning and plan the day
from. If it runs long it stops being useful — **cut hard.**

## Steps

### 1. Gather (call in parallel)
Use whichever connectors are attached; skip the rest silently:

- **Gmail** → threads from the last 24 hours with no reply.
  Search: `is:unread newer_than:2d -category:promotions -category:social`
  Also: within `is:sent newer_than:7d`, the things he is waiting on a reply for.
- **Drive** → files changed in the last three days (`list_recent_files`).
- **Scheduled tasks** → the ones running today (`list_scheduled_tasks`).
- **CLAUDE.md** and `TASKS.md` if it exists → open commitments.

### 2. Filter — this is the whole job
For every item, ask: **"will Kerem do something about this today?"**
If the answer is no, it does not go in the briefing. Newsletters,
notifications, automated mail, FYI — all rubbish.

Surface:
- Things someone is waiting on him for, where the time is nearly up
- Things he is waiting on someone else for, where the reply is late
- Deadlines, meetings or payments dated today

### 3. Write

```
# <day, date>

## 🎯 The one thing today
(If he could only do one thing today, this would be it — one sentence, with the
reason)

## ⏰ Due today
- ...   (delete this section entirely if there is nothing)

## ✉️ Waiting on a reply from you  (at most 5)
| Who | Subject | What they want | For how long |

## ⏳ You are waiting on  (people who owe him a reply — is a nudge needed?)

## 📄 Recent movement
- (Drive and file changes, only where meaningful)

## Quiet signals
- (One or two things worth noticing but not urgent. If there are none, omit.)
```

## Rules
- **One page, maximum.** If you cannot cut it down, you have not filtered enough.
- Never write an item without a source. Every line rests on an email or a file;
  link it where you can.
- If a section is empty, do not write its heading at all. An empty heading is
  noise.
- Tone: calm and neutral. Do not manufacture urgency — no "URGENT!!!".
- The last line is always: *"Which of these shall we start with?"*

## Variant
If the user says "weekly": widen the window to seven days, replace "the one
thing today" with "the three priorities this week", and add a "what finished
last week" section at the end.
