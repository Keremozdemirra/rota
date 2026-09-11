# Taste

Kerem, 2026-09-11: "zevk dedigin sey nedir, sanatsallik nedir, tasarim nedir,
ai slop nasil olunmaz, iyi is nedir. Her seyi ogret." SKILL.md beside this file
is the checklist. This is the understanding the checklist came from, so that a
chat can make the right call in a case the list never saw. Read it once at the
start of any work Kerem will look at. It is short on purpose.

## 1. What taste is

Taste is the ability to tell the better of two things and say why. The second
half is the whole skill. Anyone can prefer; a person with taste can name the
reason, and the reason holds up when a third person checks it.

It is built in one way only: by looking at a great deal of excellent work and a
great deal of poor work until the difference is visible before it is nameable,
and by making things and living with them. Robert Pirsig spent a book on the
point that quality is recognised before it can be defined (Zen and the Art of
Motorcycle Maintenance, 1974). Ira Glass gave the working version in 2009: for
years your taste runs ahead of your ability, so your own work disappoints you,
and the people who get good are the ones who keep producing through that gap
until the ability catches up. The gap is the instrument. Taste is what tells you
your own work is still short.

A practical measure: the quality of your rejections. Someone with taste
produces a first draft, looks at it, and cuts. The cut is where taste shows. A
model's default is to keep everything it made, which is why its output reads
as it does.

Taste is specific. Every good thing was made for its own case: this typeface
for this reason, this word for this reason, this margin at this width. Ask of
any element "why this and why here", and the answer either exists or the
element is decoration. Paul Graham's essay Taste for Makers (2002) lists what
good design has in common across fields; the list is worth reading once, and
the line that matters most is that good design is redesign: the first version
is where the problem is discovered.

## 2. What design is

Design is decisions. Every element on a page is a decision somebody made or
failed to make, and the reader can feel which. The difference between design
and decoration is whether the decision was made for the reader or for the
maker.

The masters agree on a small number of things:

Hierarchy. One thing on the screen is the most important thing, and the page
says which, at a glance, by size or weight or position. If two things compete,
the reader reads neither. Josef Müller-Brockmann built the grid so that the
hierarchy would hold across a hundred pages (Grid Systems in Graphic Design,
1981).

Restraint. Dieter Rams: good design is as little design as possible. His ten
principles (Vitsœ publishes them) are the shortest complete statement of the
job. Massimo Vignelli got through a career on a handful of typefaces and said
so (The Vignelli Canon, 2010, free as a PDF). The budget on any page here is
two type families and one accent colour, and the reason is Rams and Vignelli.

Honouring the content. Robert Bringhurst opens The Elements of Typographic
Style (1992) with the sentence that typography exists to honour content.
Edward Tufte says the same for data: above all else show the data, and every
mark that is not data is a candidate for deletion (The Visual Display of
Quantitative Information, 1983). Confusion and clutter are failures of design,
and he means that as a diagnosis: if a chart is hard to read, the chart is
wrong.

Affordance. Don Norman: a thing should look like what it does (The Design of
Everyday Things, 1988, revised 2013). A link looks like a link. A button that
is not a button confuses; a hover effect on a thing that cannot be clicked is
a lie told with motion.

The deletion test. Remove the element. If the page got worse, it was design.
If the page is the same or better, it was decoration and it stays gone. Run
this on every part of anything before shipping it. Deletion is the cheapest
improvement there is.

The size test. Make the thing at the size it will be seen and look at it at
that size. The margin on the case list framed a 1280 pixel page inside 320
pixels; the arithmetic said the body text was five and a half pixels tall, and
no amount of reasoning about the code would have said so. A rectangle that
size cannot hold a page. It can hold a sentence. Christopher Alexander's test
for a pattern is the same: it solves a conflict that is real at the scale
where it is applied (The Timeless Way of Building, 1979).

## 3. What artistry is

Craft is making the thing correctly. Artistry is making the thing that could
only have been made by somebody who cared about this particular thing.

The difference shows as specificity. A competent page has correct margins. A
page with life in it has a margin that is the width it is because of what
sits inside it, and a reader can feel the decision even without seeing it.
Jony Ive said that people can sense care, and he meant care in the parts they
never look at.

Artistry has a source outside the maker. Matthew Crawford's Shop Class as
Soulcraft (2009) is about this: the mechanic's standard is the engine, which
either runs or does not, and the discipline of working against a standard
you cannot argue with is where the quality comes from. On this site that
standard is the measurement. A claim ships with its number or it does not
ship. A page is checked at 390 pixels in a browser or it is not done.

Artistry is also editing. George Saunders (A Swim in a Pond in the Rain, 2021)
describes revision as reading your own sentence with a meter in your head that
swings between positive and negative, and changing the sentence until the
needle moves. That is the whole method. The first draft is material. The work
is the thousand small choices made afterwards, each one for a reason.

And it is willing to be strange. Graham's list includes that good design is
often slightly odd, because it was made for its case and its case was not the
average one. A page that could be any page has no artistry in it, however
clean.

## 4. What slop is, and why a model makes it

Slop is output produced without a decision. It is what fills a space when
nobody chose what should be there.

The mechanical tells are in SKILL.md and in the de-ai-slop-ui skill's
references/tells.md, thirty of them with a replacement each: the dash used as
a hinge, the sentence that defines a thing by what it is not, the triad for
rhythm, the adverb standing in for a fact, the quotable closer, three equal
cards with an icon, the gradient, the glass. The checker catches most of these.
The reason they exist is the thing to understand.

A model is trained on the average of a great deal of writing and design. Its
default output is therefore the mean of everything it has seen, and the mean
is generic by construction. Every tell in the list is a signature of the
average: the shape that appears most often across the training set. So the way
to avoid slop is one move, applied everywhere: make the decision the average
would not make, and be able to say why. The average uses three cards; this
page needs one, because one thing matters. The average says "thoroughly
tested"; this page says 872 assertions, because that is the number. The
average hedges with an adverb; this page states the fact or states the doubt.

Two tests, both from SKILL.md, both worth repeating because they are the ones
that work.

The swap test. Could another company put this sentence on their page
unchanged? Could another site use this layout with a different logo? Then it
says nothing about this one.

The specificity test. Does every claim carry a number or a source? Does every
element have a reason that names this page? "Keeps every task searchable in
20 milliseconds" is a claim. "A second brain" is a shape.

For prose, three older sources say the same thing and were right before there
were models: George Orwell, Politics and the English Language (1946), whose
six rules end with "break any of these rules sooner than say anything
outright barbarous"; William Zinsser, On Writing Well (1976), which is a book
about clutter; and Strunk and White's "omit needless words". Write like you
talk, and then cut.

For interfaces, the swap test has a second form: strip the colour and the type.
If the structure still reads, the design was in the structure. If it collapses
into equal grey boxes, the colour was hiding the absence of a decision.

## 5. What good work is

Good work is correct, checked, honest about its limits, and would be missed if
it were gone. Each of those is a test.

Correct and checked. Kerem's rule, from the record of building the site: if a
claim can be checked, check it before it ships; if it cannot be checked, do not
make it. Richard Feynman's Cargo Cult Science (1974) is the longer version:
bend over backwards to state everything that might be wrong with your result,
because the easiest person to fool is yourself. Two cases from this week are
the lesson. A CV sentence Kerem had retracted stayed live for two days because
two copies agreed with each other and both were stale; the fix compared them
against a third thing. And the site served with no JavaScript for an hour while
every route returned 200, because every check looked at pages and the missing
half was scripts. A check sees only what it looks at. Ask what it is not
looking at.

Honest about limits. The strongest page on the site is the one that says what
the instrument refuses to do. A tool that answers every question is a tool
that answers some of them wrong. State the refusal, state the source, state
the date the figure was true.

Would be missed. Richard Hamming's talk You and Your Research (1986) asks what
the important problems in your field are and why you are not working on them.
The small version of that question applies to every element: if this were
gone, who would notice, and what would they lose? If the answer is nobody and
nothing, it goes.

Made at the size it is seen, by a person, in the real thing. Reading the code
and reasoning about the result is how the five pixel text shipped. Open it in
a browser. Hover it. Read it on a phone. This is the pass most often skipped
and the one that finds the most.

Finished. Half a thing is not a thing. A row in NEXT.md is closed when its
"done when" is true and the log line is written, and not before. Scope is
Kerem's to cut; a chat that quietly narrows it has not finished.

## 6. How to get it

Look at excellent things, a lot of them, in the category you are working in.
For type and layout: Fonts In Use (fontsinuse.com), the Vitsœ site itself,
Brand New (underconsideration.com/brandnew), Butterick's Practical Typography
(practicaltypography.com, free, and the best single text on setting type on a
screen). For data: Tufte's four books, and any chart in The Economist. For
interfaces: Refactoring UI (Wathan and Schoger, 2018), which is practical and
short, and Bret Victor's Magic Ink (2006), which argues that most software is
graphic design and should be judged as such.

Copy a master once by hand. Retype an essay you admire. Redraw a
Müller-Brockmann poster on a grid. The point is that the hand learns the
decisions the eye slid over.

Make the thing, leave it overnight, and look at it the next day at the size it
will be seen. What embarrasses you in the morning is the note.

Write the reason beside every choice. This site's source does that in its
comments, and it is why a second person can change the site without breaking
its logic. A choice with no reason written next to it is a choice that will be
undone by the next person who touches it, including you.

Compare against the best in the category. The average is what a model
produces unprompted; matching it is the failure this file exists to prevent.

## 7. Sources

Read in this order if reading only a few.

Design
- Dieter Rams, Ten principles for good design. Vitsœ publishes the text.
- Edward Tufte, The Visual Display of Quantitative Information (1983);
  Envisioning Information (1990).
- Robert Bringhurst, The Elements of Typographic Style (1992).
- Matthew Butterick, Practical Typography (practicaltypography.com).
- Massimo Vignelli, The Vignelli Canon (2010, free PDF).
- Josef Müller-Brockmann, Grid Systems in Graphic Design (1981).
- Don Norman, The Design of Everyday Things (1988; revised 2013).
- Jakob Nielsen, Ten usability heuristics (1994). WCAG 2.2 for the contrast
  thresholds this site measures against: 4.5:1 body, 3:1 large text.
- Ellen Lupton, Thinking with Type (2004).
- Adam Wathan and Steve Schoger, Refactoring UI (2018).
- Bret Victor, Magic Ink (2006, online).
- Frank Chimero, The Shape of Design (2012, free online).
- Christopher Alexander, The Timeless Way of Building (1979); A Pattern
  Language (1977).

Writing
- George Orwell, Politics and the English Language (1946).
- William Zinsser, On Writing Well (1976).
- Strunk and White, The Elements of Style.
- George Saunders, A Swim in a Pond in the Rain (2021).
- Paul Graham, Taste for Makers (2002); Write Like You Talk (2015).

Taste and work
- Ira Glass on the gap between taste and ability (2009 interview, widely
  transcribed as "The Gap").
- Robert Pirsig, Zen and the Art of Motorcycle Maintenance (1974).
- Matthew Crawford, Shop Class as Soulcraft (2009).
- Rick Rubin, The Creative Act (2023).
- Richard Feynman, Cargo Cult Science (1974 Caltech commencement address).
- Richard Hamming, You and Your Research (1986, Bell Communications Research).

On this machine
- `~/.claude/skills/craft/SKILL.md`: the checklist, and the checker to run.
- `~/.claude/skills/de-ai-slop-ui/references/tells.md`: thirty machine tells,
  each with its replacement.
- `~/agents/kerem-pro/PRODUCT.md`: the visible text rules for the site.
- `python3 ~/agents/rota/tools/slopcheck.py FILE` before anything ships.

## 8. The whole thing in four lines

Every element has a reason that names this case, or it goes.
Every claim carries its number or its source, or it goes.
Look at the thing at the size it is seen, in the real thing, as a person.
Cut. The cut is where the taste is.
