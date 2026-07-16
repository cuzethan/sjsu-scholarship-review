// STUB scoring records built from REAL anonymized applications in materials/data
// (essays are verbatim student text, PII already stripped). the point of this
// file is to prove the review dialog renders from a rubric CONFIG (criteria,
// scale, weights, anchors) per scholarship, never a hardcoded rubric. AI scores
// + confidence below are mocked; real ones land when the scores table does.

export type Confidence = "high" | "low";

export type Category = {
  key: string;
  label: string;
  max: number;
  weight?: number; // percent, weighted rubrics only (SJSU Spartan)
  score: number;
  humanScore: number; // MOCK until IT delivers real reader scores
  confidence: Confidence;
  essayId: string | null; // null = drawn from the PS record, no essay quote
  quote?: string; // EXACT substring of that essay's text, so we can highlight it
  anchor: string; // what THIS score means, inline, so readers skip the pdf
};

export type Essay = { id: string; title: string; text: string };

export type ScoringRecord = {
  rubric: string;
  scale: string;
  weighted: boolean;
  essays: Essay[];
  categories: Category[];
  composite: number;
  compositeMax: number;
  percent: number; // AI composite normalized to 0–100 so rubrics compare
  humanPercent: number | null; // real reader score when ingested, else null
  delta: number | null; // aiPercent - humanPercent; null when no human score
};

export type Application = {
  id: string;
  student: string; // anonymized uuid, shortened for display
  scholarship: string;
  year: string;
  major: string;
  level: string;
  gpa: number | null; // some files carry 0.0 or drop the column entirely
  status: "pending" | "scored";
};

type StubApplication = Omit<Application, "status"> & { scale: string; essays: Essay[]; categories: Category[] };

// each entry = one real application + a rubric config shaped like that
// scholarship's actual rubric. quotes are literal substrings of the essays.
const STUB_APPLICATIONS: StubApplication[] = [
  {
    id: "spartan-1",
    student: "32bd…6223",
    scholarship: "SJSU Spartan",
    year: "25-26",
    major: "Business Admin/Finance",
    level: "Freshman",
    gpa: 2.259,
    scale: "weighted · 0–4",
    essays: [
      {
        id: "challenge",
        title: "Challenge or Mistake",
        text: `A challenge I have faced was my late brother's passing. It was a huge shock to everyone especially since we were so close. Receiving the call was the worst day of my life and I didn't know if I was able to recover from it. Hearing those words broke me but he was my number one supporter and I knew that he wouldn't want me to throw away everything I have accomplished and worked hard for to go to the trash. It made me realize that life is unexpected so we have to make every little thing count. I knew that things were going to change after but knew that I didn't want to stay in the hole I dug myself in, I wanted his wishes about me going to college and accomplishing everything I put my mind to. Even though he is no longer here, he will always remind me that I can do it and I am not alone.`,
      },
      {
        id: "goals",
        title: "Career Goals",
        text: `My ideal journey at SJSU is to experience college life and freedom, some may say that it's vague stating " experiencing college life". I come from a family that is dependent on me, meaning I don't have space and everyone relies on me. Moving to a new place and experiencing a whole new part of California is a game changer for me, for someone who has lived in the desert and boring cities. I now have the chance to experience something different. I am happy to have been accepted at SJSU because I know that what my mom and older brothers had to go through was not a waste. I hope to accomplish the small goals I have for myself that will lead to the bigger goal in the end. To live the life that my mom has prayed for me to have but not only satisfying my family but myself. To show myself that no obstacle is to big for me. no matter what the challenge is in front, I will overcome it. Everything I learn and experience attending SJSU will help me with my people skills and realize that I may fail in the beginning but I have to use it in the future to become a better person.`,
      },
      {
        id: "activities",
        title: "Extracurricular Activities",
        text: `What: st  Joan of arc Catholic church Where: community clean up From: august 2024 To: may 2025 Details: community clean up, teacher assistant, help with feeding the homeless  What: ASB leadership Where: commissioners From: august 2022 To: may 2025 Details: help with school events and fundraisers.`,
      },
    ],
    categories: [
      // the big-split demo app: human read the same essays much colder than the AI did
      { key: "challenge", label: "Challenge", max: 4, weight: 30, score: 3, humanScore: 2, confidence: "high", essayId: "challenge", quote: "my late brother's passing", anchor: "3 = names a real challenge and reflects on what changed" },
      { key: "goals", label: "Career Goals", max: 4, weight: 30, score: 2, humanScore: 1, confidence: "low", essayId: "goals", quote: "no obstacle is to big for me", anchor: "2 = motivation is clear but goals stay vague on next steps" },
      { key: "activities", label: "Activities", max: 4, weight: 25, score: 3, humanScore: 2, confidence: "high", essayId: "activities", quote: "community clean up, teacher assistant, help with feeding the homeless", anchor: "3 = sustained service across multiple activities" },
      { key: "academic", label: "Academic", max: 4, weight: 15, score: 2, humanScore: 2, confidence: "low", essayId: null, anchor: "2 = GPA 2.26 sits below the 2.5 comfortable band" },
    ],
  },
  {
    id: "eng-1",
    student: "1312…a3a2",
    scholarship: "Engineering",
    year: "25-26",
    major: "Applied Network Systems",
    level: "MS",
    gpa: 0.0, // file literally reads 0.0 — almost certainly missing, not a real 0
    scale: "0–5 · unweighted",
    essays: [
      {
        id: "leadership",
        title: "Leadership (College of Engineering)",
        text: `True leadership is someone who rallies others to work toward the same objectives. Leaders do not simply give commands. They are problem solvers, flexible, and goal oriented. They have initiative, empathy, and integrity. Strong marks are the hallmark of a good leader. They rise to the occasion in times of uncertainty or challenge.
My journey tells me a lot about leadership. Before studying SJSU, I worked as a computer technician and quality control. I did not hold a leadership role, but I am a natural problem-solver—I helped coworkers with technical issues, advised supervisors about where efficiencies could be made, and I worked to maintain quality in products. Leadership is not about a formal role so much as doing what individuals can when they can, I have mentored new hires, streamlined communication between departments, and even spent full nights at the office to help the team make a deadline.
At San Jose State University, I have continued to step up in my academic life—by collaborating effectively with peers during team projects and encouraging an inclusive environment where everyone's voice is heard. Specifically, I have taken up the role of organizing responsibilities, project managing, and ensuring that our team achieves the standard which is excellence in technical competence but also in respect.`,
      },
      {
        id: "challenge",
        title: "Challenge or Mistake",
        text: `Having to deal with extreme financial problems and uncertainty about how to pay for education every single semester has greatly tested my endurance and resolve. I kept pushing through all the pressure of the academy when at the same time I was so worried about me financially not being secure. I had times when I felt like giving up was the only way out, but I forced myself not to give up on me.

No educational barrier such as financial inconvenience ever stopped me from getting my education; I always found a way around it. I looked for advice, found resources, and stuck to what I wanted to achieve. My experience has strengthened me. It showed me the true significance of persistence, adaptability and requesting assistance and help when required.`,
      },
      {
        id: "goals",
        title: "Career Goals",
        text: `I am currently working towards a master's degree in applied network systems at SJSU. I have decided to devote my career to networks, which is constantly evolving its landscape with innovations like cloud computing, IoT, and Security of the infrastructure. I am interested to get deeper in the networking world to learn new networking in an innovative way and apply those concepts to real-world scenarios through coursework, labs, and projects at SJSU. These experiences will also enhance my leadership abilities and technical skills. Both of which are critical to my ambition of being a corporate researcher and professor in the end.`,
      },
      {
        id: "activities",
        title: "Extracurricular Activities",
        text: `What: HonorsX and Sustainability Where: Participant From: July/2023 To: December/2023 Details: I have been actively participating in team projects, seminars, and mentoring sessions to build and maintain professional and collaborative relationships within the community. The main intent is to help support the professional growth and skill development and research.`,
      },
    ],
    categories: [
      { key: "motivation", label: "Technical Motivation", max: 5, score: 4, humanScore: 4, confidence: "high", essayId: "goals", quote: "I have decided to devote my career to networks", anchor: "4 = clear, specific reason for the field" },
      { key: "leadership", label: "Leadership", max: 5, score: 4, humanScore: 4, confidence: "high", essayId: "leadership", quote: "I have mentored new hires, streamlined communication between departments", anchor: "4 = real leadership shown through concrete actions" },
      { key: "resilience", label: "Resilience", max: 5, score: 4, humanScore: 4, confidence: "high", essayId: "challenge", quote: "I forced myself not to give up on me", anchor: "4 = adversity handled with ownership" },
      { key: "academic", label: "Academic (GPA band)", max: 5, score: 1, humanScore: 2, confidence: "low", essayId: null, anchor: "GPA reads 0.0 in file — likely missing, flag for a human" },
    ],
  },
  {
    id: "phys-1",
    student: "e440…db66",
    scholarship: "Physics",
    year: "25-26",
    major: "Astrophysics",
    level: "Freshman",
    gpa: 2.943,
    scale: "tiered · 1–5",
    essays: [
      {
        id: "challenge",
        title: "Challenge or Mistake",
        text: `One of the most significant challenges I faced was during my first drone race in Guangzhou in 2015. Despite my enthusiasm and months of preparation, I placed sixth out of hundreds of participants from all around the country. The experience was humbling, as I realized my technical knowledge and skills were insufficient to compete at a higher level. This setback could have discouraged me, but instead, it ignited my determination to improve.

Drawing on the Kaizen philosophy my father taught me—continuous, incremental improvement—I dedicated myself to refining every aspect of my drone operation. I disassembled and upgraded my drones, experimented with lighter batteries, and studied aerodynamics and aviation rules. I also practiced relentlessly, often waking up at 5 a.m. to train before school. This persistence paid off when I earned my national drone driving license in 2021 and went on to win multiple national competitions.

This experience taught me resilience and the value of embracing failure as a stepping stone to growth. It also deepened my belief in the power of small, consistent improvements over time. This perspective continues to guide me as I pursue my dream of advancing drone technology and contributing to innovation in the field.`,
      },
      {
        id: "goals",
        title: "Career Goals",
        text: `As an international freshman, I aim to leverage my passion for drones and astrophysics to create impactful projects during my four years at SJSU.

1. Launch "Unforgettable California Journey": Collaborate with engineering and film students to provide aerial video souvenirs for tourists, expanding to major U.S. landmarks.
2. Form "SJSU Spartan Drone Racing Team" for national and international competitions.
3. Organize "MyBestDrone": Campus-wide design competitions to foster drone innovation.

To achieve these goals, I will excel in physics, materials science, engineering, and business management. My vision is to position SJSU as a leader in drone technology and entrepreneurship, balancing innovation with practical community applications.`,
      },
    ],
    categories: [
      { key: "research", label: "Research Promise", max: 5, score: 4, humanScore: 5, confidence: "low", essayId: "goals", quote: "I aim to leverage my passion for drones and astrophysics to create impactful projects", anchor: "looks like 3–4: strong interest, but no research history in file" },
      { key: "adversity", label: "Overcoming Adversity", max: 5, score: 5, humanScore: 5, confidence: "high", essayId: "challenge", quote: "I placed sixth out of hundreds of participants", anchor: "looks like 5: real setback met with sustained effort" },
      { key: "academic", label: "Academic", max: 5, score: 3, humanScore: 4, confidence: "low", essayId: null, anchor: "GPA 2.94; rubric also expects faculty rec + need, not in file" },
    ],
  },
  {
    id: "lurie-1",
    student: "f796…7e32",
    scholarship: "Lurie Education",
    year: "25-26",
    major: "Primary Education",
    level: "—",
    gpa: null, // Lurie report has no GPA column for this row
    scale: "0–10",
    essays: [
      {
        id: "coed",
        title: "Career Goals (Lurie College of Education)",
        text: `Education has and always will be extremely important to me. Not only do I think that education and academics are very important, but so are the connections that students have with their peers, teachers, and other school personnel. Being a central part of my community is important to me because, as a student, I relied on my teachers to be a central part of my community. When I lost my father when I was thirteen years old, my school and the community stepped up for my family. In a time that could have been so isolating to us, we were greeted with warmth which gave us the strength to carry on. Being a central part of the community will positively impact my students' lives because I will be a trusted adult that they can come to in times of hardship. It will also allow me to give back to the community that I grew up in.`,
      },
      {
        id: "challenge",
        title: "Challenge or Mistake",
        text: `When I was in eighth grade, I lost my dad suddenly when he died from a heart attack. To this day, that is one of the biggest challenges I have ever had to face. Shortly after my dad passed away, I thought that it was something that I would be able to "just get over". As more and more time passed, I realized that was not the case. Approximately one year after my dad passed away, I attended a grief camp for children called Camp Erin. At Camp Erin I was able to connect with other children who had lost a parent and learn healthy coping strategies. I learned that I was not alone in the way I was feeling. Without going through what I did, I would not be the person I am today. I am a more empathetic person than I was before and I have a constant reminder that you never know what someone else is going through. As a future educator, it is important to me to remind my students that we must have empathy towards everyone because today might be their hardest day.`,
      },
      {
        id: "goals",
        title: "Career Goals (General)",
        text: `During my time at SJSU, I hope to gain and/or grow valuable skills such as teamwork, collaboration, and accountability. These are just some of the extremely valuable skills that will help serve me as a future primary school educator. Through building my teamwork skills, I will understand how important it is to collaborate with my peers. This will continue to benefit me as an educator because I can employ those practices in my own classroom. Not to mention the fact I can use teamwork and collaboration with my colleagues in order to best serve our students.`,
      },
    ],
    categories: [
      { key: "commitment", label: "Commitment to Education", max: 10, score: 8, humanScore: 8, confidence: "high", essayId: "coed", quote: "Education has and always will be extremely important to me", anchor: "8 = strong, specific commitment to the field" },
      { key: "story", label: "Personal Story", max: 10, score: 9, humanScore: 9, confidence: "high", essayId: "challenge", quote: "When I was in eighth grade, I lost my dad suddenly", anchor: "9 = compelling, well-told, tied back to teaching" },
      { key: "community", label: "Community", max: 10, score: 7, humanScore: 8, confidence: "low", essayId: "coed", quote: "my school and the community stepped up for my family", anchor: "7 = clear community tie, forward impact still forming" },
    ],
  },
];

// AI and human land past this many percent-points apart -> flag for a tiebreaker.
// percent-based because the 4 rubrics have different scales (/100, /20, /15, /30).
export const DIVERGENCE_THRESHOLD = 15;

// weighted rubrics normalize to a /100 composite; unweighted just sum points.
// percent normalizes every rubric to 0–100 so the table can compare across them.
function compositeOf(categories: Category[], pick: (c: Category) => number) {
  const weighted = categories.some((c) => c.weight != null);
  const composite = weighted
    ? Math.round(categories.reduce((sum, c) => sum + (pick(c) / c.max) * (c.weight ?? 0), 0))
    : categories.reduce((sum, c) => sum + pick(c), 0);
  const compositeMax = weighted ? 100 : categories.reduce((sum, c) => sum + c.max, 0);
  return { weighted, composite, compositeMax, percent: Math.round((composite / compositeMax) * 100) };
}

function scoreSummary(categories: Category[]) {
  const ai = compositeOf(categories, (c) => c.score);
  const human = compositeOf(categories, (c) => c.humanScore);
  const lowCount = categories.filter((c) => c.confidence === "low").length;
  return { weighted: ai.weighted, composite: ai.composite, compositeMax: ai.compositeMax, percent: ai.percent, humanPercent: human.percent, lowCount };
}

// the table row = the application + its AI score summary (no essay payload).
export type TableRow = Application & {
  aiComposite: number;
  aiCompositeMax: number;
  aiPercent: number;
  humanPercent: number | null; // real reader score when ingested, else null
  delta: number | null; // aiPercent - humanPercent; null when no human score
  needsHuman: boolean; // past threshold OR any low-confidence category
  lowCount: number;
};

function toRow(row: Omit<Application, "status">, ai: number, aiMax: number, aiPercent: number, humanPercent: number, lowCount: number): TableRow {
  const delta = aiPercent - humanPercent;
  return {
    ...row, status: "scored",
    aiComposite: ai, aiCompositeMax: aiMax, aiPercent, humanPercent, delta, lowCount,
    needsHuman: Math.abs(delta) >= DIVERGENCE_THRESHOLD || lowCount > 0,
  };
}

// filler rows so the triage piles read like a real batch. table-only (no essays);
// opening one shows the detailed stub record for that scholarship.
const EXTRA_ROWS: Array<Omit<Application, "status"> & { ai: number; aiMax: number; human: number; lowCount: number }> = [
  { id: "spartan-2", student: "9a01…4c7d", scholarship: "SJSU Spartan", year: "26-27", major: "Business Analytics", level: "Junior", gpa: null, ai: 72, aiMax: 100, human: 70, lowCount: 0 },
  { id: "spartan-3", student: "77c2…e0b1", scholarship: "SJSU Spartan", year: "25-26", major: "Psychology", level: "Sophomore", gpa: 3.12, ai: 45, aiMax: 100, human: 48, lowCount: 0 },
  { id: "spartan-4", student: "b4d8…22f9", scholarship: "SJSU Spartan", year: "26-27", major: "Nursing", level: "Senior", gpa: 3.67, ai: 38, aiMax: 100, human: 62, lowCount: 0 }, // AI colder than the human — direction matters
  { id: "eng-2", student: "5e6f…91aa", scholarship: "Engineering", year: "25-26", major: "Software Engineering", level: "Junior", gpa: 3.55, ai: 16, aiMax: 20, human: 15, lowCount: 0 },
  { id: "eng-3", student: "c8a3…07d2", scholarship: "Engineering", year: "26-27", major: "Mechanical Engineering", level: "Frosh", gpa: null, ai: 11, aiMax: 20, human: 10, lowCount: 0 },
  { id: "phys-2", student: "d1b9…6e44", scholarship: "Physics", year: "26-27", major: "Physics", level: "MS", gpa: 3.88, ai: 13, aiMax: 15, human: 13, lowCount: 0 },
  { id: "lurie-2", student: "20fe…8c35", scholarship: "Lurie Education", year: "26-27", major: "Liberal Studies", level: "Junior", gpa: 3.31, ai: 20, aiMax: 30, human: 19, lowCount: 0 },
  { id: "lurie-3", student: "6b72…d9e8", scholarship: "Lurie Education", year: "25-26", major: "Child Development", level: "Senior", gpa: 3.49, ai: 27, aiMax: 30, human: 20, lowCount: 1 }, // AI warmer than the human
];

export const STUB_ROWS: TableRow[] = [
  ...STUB_APPLICATIONS.map(({ scale, essays, categories, ...row }) => {
    const { composite, compositeMax, percent, humanPercent, lowCount } = scoreSummary(categories);
    return toRow(row, composite, compositeMax, percent, humanPercent, lowCount);
  }),
  ...EXTRA_ROWS.map(({ ai, aiMax, human, lowCount, ...row }) =>
    toRow(row, ai, aiMax, Math.round((ai / aiMax) * 100), Math.round((human / aiMax) * 100), lowCount),
  ),
];

type AppLike = { scholarship: string };

export function buildStubRecord(app: AppLike): ScoringRecord {
  const entry = STUB_APPLICATIONS.find((a) => a.scholarship === app.scholarship) ?? STUB_APPLICATIONS[0]!;
  const { weighted, composite, compositeMax, percent, humanPercent } = scoreSummary(entry.categories);
  return { rubric: entry.scholarship, scale: entry.scale, weighted, essays: entry.essays, categories: entry.categories, composite, compositeMax, percent, humanPercent, delta: percent - humanPercent };
}
