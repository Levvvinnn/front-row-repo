---
name: front-row
description: Catches every moment a professor hints at what's on the exam in the student's lecture recordings, matches each hint to the Canvas slides, and sends the list before the exam. Use when the student sends a lecture recording, voice memo, video or transcript, asks what will be on an exam, or asks for their Front Row list for a class.
---

# Front Row

Professors tell students what's on the exam all the time: "this will be on the test", "know this", "people
always get this wrong". Most students miss it. Front Row listens for them. The student records the lecture and
sends it; Cubbie finds every hint, matches it to the slides on Canvas, keeps a running list for each class, and
sends that list before the exam.

This Skill uses only Cubbie's built-in abilities. It has no scripts.

## When to use

- The student sends a voice memo, audio file, video or pasted transcript of a lecture
- "Here's today's BIO lecture"
- "What's going to be on the CHEM midterm?"
- "Send me my Front Row list for MAT 265"
- "Start Front Row for my classes"

Do not use it for general studying, summarizing notes from photos, or making a study plan.

## 1. First time: set up the classes

Check memory first and skip anything already known. Ask one question at a time, with a default the student
can accept with "yes".

1. Read the student's current courses and their meeting days and times from **Canvas** (and the student's
   **calendar** if connected). If Canvas isn't connected, ask which classes they want Front Row for and when
   they meet.
2. Find upcoming exams for each class: Canvas assignments or calendar events named exam, midterm, final, test or
   quiz, and exam dates in the syllabus. Save them to memory with the class.
3. Once per class, remind the student in one line to check the syllabus allows recording, and to keep
   recordings for their own studying. If the syllabus says no recording, say so and skip that class.
4. Offer an optional "hit record" text a few minutes before each class: "Want a 🎙️ reminder 2 minutes before
   each class?" Create it only after a yes.

## 2. When a recording arrives

1. **Which class?** Match the time the recording was made or sent to the class schedule. If one class fits,
   say which one you assumed ("Got it, BIO 181 from today"). If unsure, ask: "Which class is this? BIO 181?"
2. **Transcribe it** with Cubbie's ability to transcribe voice notes and videos. If the student sent a text
   transcript (for example from the iPhone Voice Memos transcript), use that instead.
   If the recording is too long or transcription fails, ask the student to send the Voice Memos transcript
   as text, or split the recording into 2 or 3 parts. Don't stop at the first failure without offering one of these.
3. **Find the hints.** Read the whole transcript and find moments where the professor signals exam content.
   Rank each one:
   - 🔥 **Direct**: says it will be on the exam, test or quiz; "you need to know this"; "I'd study this";
     "this shows up every year".
   - ⚠️ **Strong**: "this is important", "remember this", "write this down", "if you remember one thing",
     "people always get this wrong", "this type of problem".
   - 👀 **Repeated**: a concept the professor comes back to 3 or more times in the lecture.
   Understand meaning, not just keywords: "you'll see this again in two weeks, wink" counts; "this isn't on
   the exam" is the opposite and should be saved as a **skip** ("not on the exam").
4. For each hint, keep: the concept in a few plain words, its rank, roughly where in the recording it was
   (minutes in), and a short line of what the professor said (under 15 words).
5. **Match to Canvas.** Search the course materials on Canvas for each concept and find the slide deck, page or
   file that covers it. Save the link. If nothing on Canvas covers it, mark it **Only said in lecture**. These
   are the most valuable hints, because classmates who only read the slides will miss them.
6. Save each hint to memory under the class, with the lecture date. Don't save the full transcript to memory.
   Offer the full transcript as a document if the student wants it.

Never invent a hint. Every hint must come from something the professor actually said in a recording the
student sent. If the audio is unclear at a key moment, say so instead of guessing.

## 3. Reply after each lecture

Lead with the count and the best hint, then the rest briefly. Show at most 4 hints in the text; if there are
more, say how many and offer the full list.

## 4. Before the exam

Offer two check-ins per exam, created only after the student says yes:

- **7 days before**: send the full Front Row list for that class.
- **The night before**: send only the 🔥 Direct hints and anything marked Only said in lecture.

Word each check-in so it makes sense on its own later: "Front Row check-in for <class> <exam name> on
<date>: read the saved hints for this class from memory, check Canvas for any change to the exam date, and
send the <full list / night-before short list>."

For the full list, make a one-page PDF titled "Front Row: <class> <exam>". Group hints by topic, 🔥 first, then
⚠️, then 👀. For each hint: the concept, what the professor said, the lecture date, and the Canvas link or "Only
said in lecture". End with a short "Said NOT on the exam" section if there are skips. Add one quick self-check
question for each 🔥 hint. Send the PDF with a one-line summary.

If the exam date changes on Canvas, update the saved date and move the check-ins, and tell the student in one line.

## 5. After the exam (optional)

The day after an exam, ask once: "How many hints showed up on the exam? 🎯" Save the answer. It helps the student
see which kinds of hints this professor really means, and it's great to share.

## Replies

Short, plain text, one idea per message, no Markdown symbols. Sound like a friend who sat in the front row and
took good notes. Put links on their own line. Never promise that a hint will be on the exam; say what the
professor said and let the student decide.

After a lecture:

```text
BIO 181 today: 3 hints 🔥

🔥 Krebs cycle products, she said "this WILL be on the midterm" (min 34)
⚠️ ATP yield per glucose, "people always get this wrong"
👀 Electron transport chain, came back to it 4 times

The ATP one isn't in the slides. Only said in lecture.
```

A week before:

```text
BIO 181 Midterm is Thursday. Your Front Row list: 11 hints from 7 lectures, 4 of them 🔥

Full list attached 📎
```

The night before:

```text
Tomorrow's BIO midterm. The 🔥 ones:
- Krebs cycle products
- Glycolysis net ATP
- Mitochondria structure diagram
- ATP yield (only said in lecture)

You got this 🍀
```

## When something fails

- Transcription fails or the file is too long: "That one was too long for me. Can you send the Voice Memos
  transcript, or split it into 2 parts?"
- No hints found: say so honestly, and name the concept the professor spent the most time on.
- Can't tell which class: ask once, with the most likely class as the default.
- Canvas not connected: still find hints; skip slide matching and ask the student for the exam date.
- No exam date found: ask "When's the next exam in BIO 181?" and save it.
- Poor audio: say which part was hard to hear, and suggest putting the phone on the desk next time.
