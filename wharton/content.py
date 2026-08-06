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
