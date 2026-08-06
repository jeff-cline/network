#!/usr/bin/env python3
"""
Source content for whartonjelly.com.

Every clinical or regulatory sentence here is quoted from material the operator
supplied or from iore.com. Nothing clinical is paraphrased or invented, because
this is a regulated space and the source material itself is explicit that
"stem cells" language and disease-treatment claims are the risk.

The manufacturer is never named. IORE is cited as the education and clinical
support hub, which is how the supplied material describes it.
"""

BRAND = "Wharton Jelly"
TAGLINE = "The premier biologic for precision medicine."
SUBLINE = "Individualized precision medicine is the future of health care."

# --- verbatim from iore.com -------------------------------------------------
IORE_URL = "https://www.iore.com/"
IORE_NAME = "Institute of Regenerative Education"
IORE_HEADLINE = "Empowering the Next Generation of Regenerative Medicine Leaders"
IORE_SUB = "Advancing Education & Research in Biologics"
IORE_BULLETS = [
    "Access evidence based treatment protocols curated by Dr. Scott Martin",
    "Advance your skills with cutting-edge regenerative therapy knowledge",
    "Earn recognition for your commitment to evidence-based regenerative medicine",
    "Seek individualized advice for your practice",
    "Navigate the complex landscape of regenerative medicine safely and compliantly",
    "Connect with a community of regenerative professionals",
]
IORE_FEATURES = ["IORE Registry", "Book Peer-To-Peer", "IORE Certification", "Upcoming Events"]

# The compliance notice, quoted exactly. Shown on every page.
COMPLIANCE = ("This content is provided for educational purposes and research use only (RUO). "
              "It reflects the professional experience and academic perspectives of credentialed "
              "providers and is not intended to diagnose, treat, cure, or prevent any disease. "
              "Clinical application and regulatory compliance remain the responsibility of the "
              "licensed provider.")

# --- verbatim from the supplied provider material ---------------------------
HUB_INTRO = ("In partnership with our outside medical board, we have launched IORE, our dedicated "
             "educational platform created to support you well beyond your initial order.")
HUB_ITEMS = [
    "On-demand educational content and clinical training",
    "Regenerative Medicine Certification Course",
    "Recommended protocols and evolving best practices",
    "A peer-to-peer booking link for complimentary medical consulting with Dr. Scott Martin, "
    "Head of our Outside Medical Board",
    "Clinical resources designed to support confidence, compliance, and growth",
]
HUB_CLOSE = ("IORE is designed to be your go-to resource as you integrate and scale biologic "
             "applications within your practice.")

# Educational modules — descriptions quoted from the supplied material.
MODULES = [
    {
        "slug": "talking-to-patients",
        "title": "How do we talk to patients about “Stem Cells”?",
        "audience": "provider",
        "body": ("When presenting human cell and tissue products (HCTPs) to patients, providers "
                 "should avoid unregulated terms like “stem cells” and instead focus on "
                 "tissue-specific supplementation for cartilage-based defects, explaining that "
                 "these products supply collagenic growth factors (like type I, II, and III "
                 "collagen) that may help the body heal itself at a cellular level—especially "
                 "when inflammation is controlled. By using FDA-aligned language, discussing "
                 "patient-specific regenerative capacity, and matching graft complexity to injury "
                 "severity and age, clinicians can ethically and effectively guide patients "
                 "through their options."),
    },
    {
        "slug": "regulatory-environment",
        "title": "Regulatory Environment Around Stem Cells — Dispelling Myths",
        "audience": "provider",
        "body": ("Dr. Martin delivers a critical and detailed overview of the U.S. regulatory "
                 "landscape surrounding stem cells, emphasizing that using the term “stem "
                 "cells” in clinical practice is scientifically inaccurate and legally risky. "
                 "He explains that current compliant use involves human cell and tissue products "
                 "(HCTPs) like Wharton's Jelly, which are structural allografts meant to "
                 "supplement local cartilage defects—not regenerate tissue or treat systemic "
                 "diseases like osteoarthritis, which would constitute unapproved drug claims."),
    },
    {
        "slug": "are-stem-cells-a-scam",
        "title": "Are Stem Cells a Scam?",
        "audience": "provider",
        "body": ("Dr. Martin addresses the misconception that “stem cells” are a cure-all, "
                 "emphasizing that successful regenerative outcomes depend not on magical products "
                 "but on proper clinical application rooted in scientific understanding—"
                 "especially of collagenic differentiation. He urges providers to move beyond "
                 "marketing hype, deepen their knowledge of biologic mechanisms, and practice "
                 "evidence-based medicine if they want to stay competitive and deliver meaningful "
                 "patient results."),
    },
    {
        "slug": "allogeneic-science",
        "title": "The basics behind Allogeneic Science",
        "audience": "provider",
        "body": ("Dr. Martin offers a science-based explanation of how allografts—particularly "
                 "Wharton's Jelly—contribute to structural support and localized tissue "
                 "optimization through collagenic signaling. He encourages providers to move beyond "
                 "the outdated “stem cell” terminology and focus on the well-characterized "
                 "growth factor profiles found in structural tissue allografts. Dr. Martin also "
                 "underscores the importance of using these materials within defined, localized "
                 "applications and cautions against making non-compliant claims related to systemic "
                 "effects or disease reversal."),
    },
    {
        "slug": "understanding-regenerative-medicine",
        "title": "Understanding Regenerative Medicine",
        "audience": "consumer",
        "body": ("Providers are now playing this video on an iPad for their patients before "
                 "consultation to better explain the regenerative options offered, helping to "
                 "warm-up the close for their treatment plan. Dr. Martin explains the benefits of "
                 "regenerative therapies, particularly umbilical cord tissue-derived products like "
                 "Wharton's Jelly and their role in down-regulating inflammation and supplying "
                 "essential collagen for joint repair. As we age, our bodies lose the ability to "
                 "produce vital collagen types, which can hinder recovery from injuries. He "
                 "emphasizes that these products are not drugs and do not treat diseases, but they "
                 "can support your body's natural healing processes."),
    },
]

FB_GROUP = "https://www.facebook.com/groups/7083242121790855/"
FB_NOTE = "a private group with over 200+ hours of educational content"

# Image slots the operator can replace from the back office.
IMAGE_SLOTS = [
    ("hero_poster",   "Hero video poster frame"),
    ("provider_1",    "Provider portfolio — clinical training"),
    ("provider_2",    "Provider portfolio — protocols"),
    ("provider_3",    "Provider portfolio — certification"),
    ("consumer_1",    "Patient education — what it is"),
    ("consumer_2",    "Patient education — what to ask"),
    ("science_1",     "Allogeneic science"),
]


# Footer enquiry desks. Each renders the same styled form and routes to the JV
# pipeline, so partnership interest is captured with the same rigour as leads.
CONNECT = [
    ("investor-relations", "Investor Relations",
     "Financials, growth and the shape of the opportunity.",
     "Tell us about your firm and what you are looking to understand."),
    ("media-press", "Media & Press",
     "Interviews, commentary and background for journalists.",
     "Your outlet, deadline and the angle you are working on."),
    ("advertise", "Advertise With Us",
     "Reach clinicians building regenerative practices.",
     "Your product or service and the audience you want to reach."),
    ("sponsor", "Sponsor Us",
     "Education, events and clinical programming.",
     "What you would like to sponsor and at what level."),
    ("become-a-provider", "Become a Provider",
     "Advanced support, documentation, protocols and product access.",
     "Your practice, speciality and where you are in the process."),
    ("manufacturers", "Manufacturers",
     "Supply, tissue sourcing and distribution partnerships.",
     "What you manufacture and the partnership you have in mind."),
    ("links", "Links",
     "Partnerships, referrals and reciprocal links.",
     "Your site and the kind of link relationship you are proposing."),
]

FAQ = [
    ("What is Wharton's Jelly?",
     "Wharton's Jelly is a human cell and tissue product (HCTP). As described in our clinical "
     "education material, these are structural allografts meant to supplement local cartilage "
     "defects."),
    ("Are these products drugs?",
     "No. As stated in our patient education material: these products are not drugs and do not "
     "treat diseases, but they can support your body's natural healing processes."),
    ("Why do you avoid the term \u201cstem cells\u201d?",
     "Our clinical education material is explicit: providers should avoid unregulated terms like "
     "\u201cstem cells\u201d and instead focus on tissue-specific supplementation for "
     "cartilage-based defects. Using the term in clinical practice is described as "
     "scientifically inaccurate and legally risky."),
    ("What do these products actually supply?",
     "They supply collagenic growth factors (like type I, II, and III collagen) that may help the "
     "body heal itself at a cellular level\u2014especially when inflammation is controlled."),
    ("Who validates the education?",
     "Education and clinical support are provided through the Institute of Regenerative "
     "Education, an independent third party, with protocols curated by Dr. Scott Martin."),
    ("How do patient referrals work?",
     "Patients who register are matched by ZIP code to a participating provider. Providers "
     "control whether they receive referrals, and a provider may hold a ZIP exclusively."),
]


# Every destination we are willing to send a visitor to. The outbound gate only
# redirects to something on this list — a free-form redirect parameter would be
# an open redirect anyone could abuse to launder a phishing link off our domain.
OUTBOUND = {
    "iore":     (IORE_URL, IORE_NAME,
                 "Our education and clinical validation partner, an independent third party."),
    "iore-cert": ("https://www.iore.com/", "IORE Certification",
                  "Regenerative Medicine Certification Course."),
    "community": (FB_GROUP, "Private clinical community", FB_NOTE.capitalize() + "."),
}


# --- video library -----------------------------------------------------------
# Descriptions are quoted from the supplied material. Only entries with a real
# URL play; the rest are visible placeholders the operator fills from the back
# office. Nothing here invents a video that does not exist.
FEATURED_VIDEO = {
    "slug": "understanding-regenerative-medicine",
    "title": "Understanding Regenerative Medicine",
    "speaker": "Dr. Scott Martin",
    "audience": "both",
    "category": "Patient education",
    "url": "https://www.loom.com/share/a149edd7eb77456ab237f81318571516",
    "embed": "https://www.loom.com/embed/a149edd7eb77456ab237f81318571516",
    "runtime": "",
    "quote": ("Hello, I\u2019m Dr. Martin, and in this video, I explain the benefits of "
              "regenerative therapies, particularly umbilical cord tissue-derived products like "
              "Wharton's Jelly and their role in down-regulating inflammation and supplying "
              "essential collagen for joint repair. As we age, our bodies lose the ability to "
              "produce vital collagen types, which can hinder recovery from injuries. I emphasize "
              "that these products are not drugs and do not treat diseases but can support your "
              "body\u2019s natural healing processes. I encourage you to do your own research on "
              "these therapies and have an open dialogue with your provider about how they might "
              "fit into your recovery plan. Thank you for your time, and I wish you good health."),
    "blurb": ("Dr. Martin explains what these products are, what they are not, and how to talk "
              "to your provider about them."),
}

VIDEO_CATEGORIES = [
    ("patient-education", "Patient education", "consumer",
     "What these products are, in plain language."),
    ("compliance", "Compliance & regulatory", "provider",
     "Language, claims and the regulatory landscape."),
    ("clinical-science", "Clinical science", "provider",
     "Mechanism, allogeneic science and graft selection."),
    ("practice-growth", "Practice & patient conversations", "provider",
     "Presenting options and building patient confidence."),
]

VIDEOS = [
    {"slug": "understanding-regenerative-medicine", "audience": "consumer",
     "category": "patient-education", "title": "Understanding Regenerative Medicine",
     "speaker": "Dr. Scott Martin",
     "embed": "https://www.loom.com/embed/a149edd7eb77456ab237f81318571516",
     "desc": ("Dr. Martin explains the benefits of regenerative therapies, particularly umbilical "
              "cord tissue-derived products like Wharton's Jelly and their role in "
              "down-regulating inflammation and supplying essential collagen for joint repair. As "
              "we age, our bodies lose the ability to produce vital collagen types, which can "
              "hinder recovery from injuries. He emphasizes that these products are not drugs and "
              "do not treat diseases, but they can support your body's natural healing "
              "processes.")},
    {"slug": "talking-to-patients", "audience": "provider", "category": "practice-growth",
     "title": "How do we talk to patients about \u201cStem Cells\u201d?", "speaker": "Dr. Scott Martin",
     "embed": "",
     "desc": ("When presenting human cell and tissue products (HCTPs) to patients, providers "
              "should avoid unregulated terms like \u201cstem cells\u201d and instead focus on "
              "tissue-specific supplementation for cartilage-based defects, explaining that these "
              "products supply collagenic growth factors (like type I, II, and III collagen) that "
              "may help the body heal itself at a cellular level\u2014especially when inflammation "
              "is controlled.")},
    {"slug": "regulatory-environment", "audience": "provider", "category": "compliance",
     "title": "Regulatory Environment Around Stem Cells \u2014 Dispelling Myths",
     "speaker": "Dr. Scott Martin", "embed": "",
     "desc": ("A critical and detailed overview of the U.S. regulatory landscape surrounding stem "
              "cells, emphasizing that using the term \u201cstem cells\u201d in clinical practice "
              "is scientifically inaccurate and legally risky.")},
    {"slug": "are-stem-cells-a-scam", "audience": "provider", "category": "compliance",
     "title": "Are Stem Cells a Scam?", "speaker": "Dr. Scott Martin", "embed": "",
     "desc": ("Dr. Martin addresses the misconception that \u201cstem cells\u201d are a cure-all, "
              "emphasizing that successful regenerative outcomes depend not on magical products "
              "but on proper clinical application rooted in scientific understanding\u2014"
              "especially of collagenic differentiation.")},
    {"slug": "allogeneic-science", "audience": "provider", "category": "clinical-science",
     "title": "The basics behind Allogeneic Science", "speaker": "Dr. Scott Martin", "embed": "",
     "desc": ("A science-based explanation of how allografts\u2014particularly Wharton's "
              "Jelly\u2014contribute to structural support and localized tissue optimization "
              "through collagenic signaling.")},
]
