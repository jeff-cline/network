"""Marketing and educational content for each product line.

Written to explain why a person would buy the thing, not to restate the
brochure. No invented statistics — the case for each product is made from how
the coverage actually behaves against how people actually get hurt and billed.
"""

BRAND = "Policy Store"
TAGLINE = "The first fully autonomous insurance agency."
PHONE = "972-800-6670"
OWNER_EMAIL = "jeff.cline@me.com"

HERO = {
    "kicker": "Fully autonomous insurance agency",
    "h1": "Get quoted, covered and confirmed — without waiting for a human.",
    "sub": ("Answer three questions and get a real quote from the carrier's own rate sheet. "
            "Enroll by text. Pay through the administrator. All of it in one conversation, at "
            "any hour, with a thirty-day free look on the other side."),
}

FREE_LOOK = ("Every policy carries a 30-day free look. Read it, sit with it, and if it is not "
             "for you, cancel within thirty days for a full refund of premium — provided no "
             "claim has been filed against the policy.")

PRODUCTS = {
    "add": {
        "name": "Accidental Death & Dismemberment",
        "short": "AD&D",
        "icon": "🛡️",
        "tag": "The coverage that pays when the unthinkable is also the unexpected.",
        "lede": ("AD&D pays a benefit if a covered accident causes death, or the loss of a limb, "
                 "sight, hearing or speech. It sits on top of everything else you have — it does "
                 "not replace your life insurance, it stacks with it."),
        "why": [
            ("It covers the risk that arrives without warning",
             "Illness gives you notice. An accident does not. AD&D is built for the category of "
             "event nobody schedules around: the drive home, the ladder, the intersection, the "
             "afternoon on the water."),
            ("It issues without a medical exam",
             "There is no physical, no blood draw and no months-long underwriting file. Age, "
             "state and the benefit amount you choose are effectively the whole conversation, "
             "which is why the quote can happen inside a phone call."),
            ("It costs a fraction of the death benefit it carries",
             "Because it only pays on accidents, the premium behaves nothing like fully "
             "underwritten life insurance. It is the cheapest way most people can put a "
             "six-figure benefit in place this week."),
            ("Dismemberment is the half nobody reads",
             "Most buyers think of the death benefit. The schedule also pays on loss of a hand, "
             "a foot, sight in an eye, hearing or speech — the outcomes that end a career "
             "without ending a life, and that no other policy in the household pays for."),
            ("Your employer's version leaves when you do",
             "Group AD&D through work ends with the job, and it is rarely portable on terms you "
             "would choose. A policy you own follows you."),
        ],
        "who": ["Anyone whose income depends on their body being intact",
                "Tradespeople, drivers, field crews and anyone who works at height or on the road",
                "Parents who want a benefit in place before they finish shopping for life cover",
                "People who were declined or rated for traditional life insurance",
                "Anyone whose only coverage is the group plan at work"],
        "faq": [
            ("What counts as a covered accident?",
             "The policy defines it, and the definition is the thing to read. Broadly, a sudden, "
             "unforeseen external event that causes injury independently of illness. Your policy "
             "documents give the exact language, exclusions included."),
            ("Does it pay on top of my life insurance?",
             "Yes. AD&D is a separate contract and pays its own benefit. It does not offset or "
             "reduce a life insurance payout."),
            ("Is there a medical exam?",
             "No. That is the practical reason this product can be quoted and issued inside a "
             "single conversation."),
            ("Can I cover my spouse and children?",
             "Yes. Coverage is written in tiers — you, you and your spouse, you and children, or "
             "the whole household. Because rates are age-banded, we will ask each adult's age."),
        ],
    },
    "ame": {
        "name": "Accident Medical Expense",
        "short": "AME",
        "icon": "🩹",
        "tag": "For the bill your health insurance hands back to you.",
        "lede": ("AME pays toward the medical costs of a covered accident — the deductible, the "
                 "copays, the coinsurance — the share your major medical plan expects you to "
                 "cover yourself."),
        "why": [
            ("High deductibles moved the risk onto you",
             "Health insurance increasingly means a large deductible before it does anything at "
             "all. An emergency room visit, an ambulance and a set of scans can exhaust that "
             "deductible in a single afternoon, and the plan works exactly as designed while you "
             "pay for it."),
            ("It pays regardless of what else you have",
             "AME is not coordinated away because you also have major medical. It is a separate "
             "benefit for a defined event, which is what makes it useful precisely when your "
             "other coverage is doing the least for you."),
            ("You choose where the coverage starts",
             "Deductible options run from zero upward. A zero-deductible plan starts paying at "
             "the first dollar of accident expense; a higher deductible trades that for a lower "
             "premium. Both are legitimate, and the right answer depends on what you keep in "
             "savings."),
            ("The events are ordinary, which is the point",
             "This is not exotic coverage. It is for the trampoline, the kitchen knife, the "
             "bicycle, the weekend league, the icy step and the fender bender — the accidents "
             "that fill emergency rooms every single day."),
            ("It protects the emergency fund you already built",
             "Most households can absorb one bad afternoon. Fewer can absorb it twice in a year "
             "without touching something they were saving for."),
        ],
        "who": ["Anyone on a high-deductible health plan",
                "Families with children in sport",
                "Self-employed people buying their own major medical",
                "Households where an unexpected few thousand dollars would genuinely hurt",
                "People who already have a deductible they know they cannot comfortably meet"],
        "faq": [
            ("How is this different from health insurance?",
             "Health insurance is the primary payer for treatment. AME pays toward what that "
             "plan leaves with you after a covered accident — the deductible and cost-sharing."),
            ("Do I have to use a specific hospital or network?",
             "AME pays a benefit for covered accident expenses; it is not a network plan. Your "
             "policy documents set out how benefits are determined."),
            ("What deductible should I pick?",
             "If an unexpected $1,000 would be a problem this month, take the lowest deductible "
             "you can afford. If you keep a healthy emergency fund, a higher deductible and a "
             "lower premium is usually the better trade."),
            ("Does it cover illness?",
             "No. AME is accident coverage. Critical Illness is the product that responds to a "
             "covered diagnosis, and the two are frequently bought together."),
        ],
    },
    "ci": {
        "name": "Critical Illness",
        "short": "Critical Illness",
        "icon": "❤️‍🩹",
        "tag": "A lump sum paid to you, for the part of illness that is not medical.",
        "lede": ("Critical Illness pays a cash benefit on a covered diagnosis. The money goes to "
                 "you rather than to a hospital, and you decide entirely what it is for."),
        "why": [
            ("Health insurance treats the illness, not the life around it",
             "It pays doctors and hospitals. It does not pay the mortgage while you are not "
             "working, cover the drive to a specialist three hours away, or fund the childcare "
             "you suddenly need five days a week."),
            ("The benefit is cash, and it is yours",
             "There is no claim form itemising what you spent it on. Rent, groceries, a spouse "
             "taking unpaid leave, a second opinion in another city — the policy does not care."),
            ("It arrives when income usually falls",
             "A serious diagnosis frequently reduces household income at the exact moment costs "
             "rise. A lump sum is the only instrument most families have that moves in the "
             "opposite direction to that shock."),
            ("It buys time, which is the scarce thing",
             "The practical value people report is not the amount. It is not having to make "
             "financial decisions in the same week as medical ones."),
            ("Coverage is straightforward to put in place",
             "Benefit amounts run from modest to meaningful, and the policy is quoted from age "
             "band and state — no exam, no long file."),
        ],
        "who": ["Single-income households",
                "Self-employed people with no sick pay behind them",
                "Anyone with a family history that keeps them up at night",
                "People whose emergency fund covers weeks rather than months",
                "Anyone who has watched a diagnosis happen to someone close and seen the cost"],
        "faq": [
            ("Which conditions are covered?",
             "The policy schedules the covered conditions and the benefit payable for each. Read "
             "that schedule — it is the single most important page in the contract."),
            ("When does it pay?",
             "On a covered diagnosis as defined in the policy, subject to its terms and any "
             "waiting periods. It does not require you to be out of work."),
            ("Can I use it however I want?",
             "Yes. It is a cash benefit paid to you."),
            ("Is it available everywhere?",
             "Not yet. Critical Illness is filed in most of our live states but not all of "
             "them — the quoter checks before it offers, and will simply not present it where "
             "it is unavailable."),
        ],
    },
    "t365": {
        "name": "Travel 365",
        "short": "Travel 365",
        "icon": "✈️",
        "tag": "Annual travel medical cover — every trip for a year, not one at a time.",
        "lede": ("Travel 365 covers a full year of travel rather than a single trip, with "
                 "protection for interruptions and cancellations, lost baggage, and sudden "
                 "illness or a medical emergency away from home."),
        "why": [
            ("Your health plan often stops at the border",
             "Domestic major medical frequently provides little or nothing abroad, and rarely "
             "arranges anything. The gap is not the cost of a doctor — it is being unwell "
             "somewhere unfamiliar with no one to call."),
            ("Annual beats per-trip once you travel more than twice",
             "Buying cover trip by trip means remembering to buy it, every time, before every "
             "departure. One annual policy removes the decision and usually costs less than "
             "three single-trip policies."),
            ("It covers the trip, not just the traveller",
             "Interruption and cancellation benefits respond to the money already spent — the "
             "flights, the deposits, the nights you paid for and did not get."),
            ("Three levels, one decision",
             "Basics, Essentials and Choice differ in limits rather than in kind. Pick the one "
             "that matches the value of the trips you actually take."),
            ("Priced per person, per year",
             "Rates vary slightly by state of residence and are published — the quote you get is "
             "the rate on the sheet."),
        ],
        "who": ["Anyone taking more than two trips a year",
                "People with family abroad who travel at short notice",
                "Remote workers and frequent business travellers",
                "Retirees travelling several times a year",
                "Anyone who has ever paid a cancellation penalty and remembered it"],
        "faq": [
            ("How long does coverage last?",
             "A full annual term covering your trips through the year. Coverage limits are "
             "aggregate amounts for that term."),
            ("Is there an age limit?",
             "Yes. Plans are not available for travellers over eighty years old."),
            ("Is it available in my state?",
             "Chubb publishes Travel 365 availability across all fifty states and the District "
             "of Columbia. A small number of states have no published rate on our sheet yet; the "
             "quoter tells you rather than guessing."),
            ("What is not included?",
             "These plans do not include the Financial Default benefit. Full terms, limits and "
             "exclusions are in the policy documents."),
        ],
    },
}

BUNDLES = [
    ("add+ame", "AD&D + Accident Medical",
     "The pairing most people actually want: a benefit if an accident is catastrophic, and help "
     "with the bill if it is merely expensive. Between them they cover both ends of the same "
     "event."),
    ("add+ci", "AD&D + Critical Illness",
     "Covers the two ways a household gets financially derailed without warning — a sudden "
     "accident and a sudden diagnosis. One pays a benefit on injury, the other on illness."),
    ("ame+ci", "Accident Medical + Critical Illness",
     "Both products pay toward what your health plan hands back to you: the accident bill on one "
     "side, and the cost of living through a diagnosis on the other."),
]

WHY_AUTONOMOUS = [
    ("🕐", "Always on",
     "Two in the morning, a holiday weekend, or the hour after something frightening happened to "
     "someone you know. The agent answers, every time, with no queue."),
    ("🛡️", "It mitigates risk",
     "The same approved script on every call, quoting only carrier-filed rates, captured end to "
     "end. No off-script statements and no promises the policy does not make."),
    ("💸", "No employment overhead",
     "No salary, benefits, holiday, sick pay, overtime, recruiting or attrition. Capacity scales "
     "with demand rather than headcount."),
    ("⚡", "Three questions to a quote",
     "Age, state and what you want to spend. Everything else the agent needs, it already knows "
     "from the rate sheet."),
    ("📱", "Enroll by text",
     "A short link lands on your phone while you are still on the line. Pay through the "
     "administrator — no card details are ever spoken aloud or recorded."),
    ("↩️", "30-day free look",
     "Read the policy at home. Cancel inside thirty days for a full refund of premium, as long "
     "as no claim has been filed."),
]

COMPLIANCE = ("Policy Store is an insurance agency. Coverage is underwritten by the carrier named "
              "in your policy documents. This site describes products in general terms and is not "
              "a contract; benefits, limitations and exclusions are governed entirely by the "
              "policy as issued. Product availability, benefit amounts and rates vary by state. "
              "This is a solicitation of insurance; an agent may contact you.")
