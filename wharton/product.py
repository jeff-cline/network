#!/usr/bin/env python3
"""
Product, science and sourcing copy for whartonjelly.com.

Wording is as supplied, with two deliberate substitutions and one typo fix,
each recorded here so the change is auditable rather than silent:

  "Platinum Biologics"  -> neutral phrasing ("our", "we")
      The operator has instructed that the manufacturer is never named on this
      white-label site. Leaving it in the sourcing copy would defeat the whole
      arrangement, since that section is the most likely to be read closely.

  "RenewXO"             -> "WJ-SS"
      Another manufacturer brand. The supplied vial artwork is labelled WJ-SS
      over whartonjelly.com, so that is this site's product name.

  "per vile"            -> "per vial"
      Plain typo in the supplied headline. Kept as "vial" because a misspelling
      in an H3 on a clinical page costs more credibility than it preserves.

The legal footer text is reproduced exactly and is not touched.
"""

PRODUCT = {
    "name": "WJ-SS",
    "h2": "MSC Wharton's Jelly Derived Formulation",
    "h3": "10 Billion Lyophilized Exosomes per vial",
    "image": "/static/img/wj-ss-vial.png",
    "image_alt": ("WJ-SS vial — lyophilized Wharton's Jelly derived formulation in a clear "
                  "amber-free glass vial with an aluminium seal"),
    "sections": [
        ("Discover the Science",
         "Through extensive research and development, Wharton Jelly Shelf Stable (WJST) blends "
         "the perfect fusion of science and nature. We start with umbilical cord-derived "
         "exosomes, known for their exceptional potency in Placental, Vascular Endothelial, and "
         "Transforming growth factors. This unique acellular formulation of growth factors, "
         "exclusive to WJ-SS, creates application flexibility unrivaled by other products."),
        ("Convenience Meets Potency",
         "WJST is a shelf-stable product that requires no refrigeration. Our Lyophilization "
         "process dehydrates without denaturing the crucial peptides, proteins, and growth "
         "factors essential for collagen-based healing. This means you can safely apply WJ-SS "
         "based on patient needs."),
        ("Transparency and Trust",
         "We proudly disclose all ingredients, and package our product in transparent amber "
         "vials. We believe in the power of clearly seeing the purity of our products. And we "
         "guarantee that you'll be astonished by the results your clients are about to "
         "experience!"),
    ],
}

WHY = {
    "title": "Why Wharton's Jelly?",
    "paras": [
        ("Wharton's Jelly, a connective tissue found in the umbilical cord, is primarily "
         "composed of mesenchymal stem cells and various extracellular matrix components such as "
         "collagen, chondroitin sulfate, hyaluronic acid, and sulfated proteoglycans. It boasts "
         "the highest concentration of mesenchymal stem cells per milliliter compared to other "
         "tissues rich in extracellular matrix components. Additionally, Wharton's Jelly contains "
         "clinically significant growth factors, cytokines, and extracellular vesicles."),
        ("The advantages of Wharton's Jelly stem from its abundant extracellular matrix "
         "components, including collagen types I, III, and V, elastin, and fibronectin, which "
         "serve as a natural scaffold facilitating cellular adhesion."),
        ("While primarily providing cushioning and structural support to the umbilical cord, "
         "Wharton's Jelly also offers a natural source of long-chain hyaluronic acid and numerous "
         "cytokines and growth factors. Notably, placental tissues, including Wharton's Jelly, "
         "are considered “immune privileged” due to their low likelihood of triggering "
         "an immune response, reducing the risk of adverse reactions."),
    ],
}

CONNECTIVE = {
    "title": "Connective Tissue Defects",
    "paras": [
        ("Connective tissues hold the structures of the body together. They are made up of two "
         "different proteins, collagen, and elastin. Collagen is found in the tendons, ligaments, "
         "skin, cartilage, bone, and blood vessels. Elastin is located in the ligaments and skin."),
        ("Missing, damaged, or inadequate connective tissue can lead to many symptomatic issues. "
         "This compromises the structural integrity and stability of the area. Wharton's Jelly "
         "naturally provides cushioning and structural support directly to the affected area."),
    ],
}

SOURCING = [
    ("Prescreening",
     "Products are obtained from healthy, carefully screened mothers at the time of normal "
     "delivery. In addition to a stringent social screening interview, all mothers undergo "
     "serology testing to ensure there is no risk for a communicable disease. No harm is brought "
     "to the mother or her newborn and parents still have the option of storing the cord blood "
     "if desired."),
    ("Processing",
     "Recovery of tissue is performed at the time of delivery by trained technicians in a sterile "
     "environment. All processing is done in a cGMP facility following the regulations of the FDA "
     "and the guidelines of the American Association of Tissue Banks (AATB) and the American "
     "Association of Blood Banks (AABB)."),
    ("Distribution",
     "All products are shipped on dry ice in validated shipping containers to ensure appropriate "
     "temperature is maintained."),
]

SOURCING_INTRO = (
    "The field of natural biologics spans decades and comes in many different forms. New "
    "providers often ask us where our products come from and how we qualify donors before "
    "continuing with the natural biologic process. Our products are donated from consenting "
    "mothers at the time of delivery. Our products are safely cultivated and meet the highest "
    "quality assurance standards to be utilized in your clinical program.")

SOURCING_STEPS = [
    "Donors are healthy women who are thoroughly screened for any communicable diseases. A "
    "medical and social history is collected and reviewed by our Medical Director to ensure that "
    "the mother meets all the eligibility requirements.",
    "Tissues are collected after full term live births by c-section and conducted only by "
    "licensed professionals.",
    "There is a 48 hour window to process the fresh tissue after collection.",
    "All tissues are cleaned and decontaminated during processing. We follow strict protocols to "
    "make sure our tissue is free of pathogens.",
    "Each tissue is uniquely identified by lot. Each lot is processed and is adherent to all "
    "applicable regulations.",
    "Preservation of product viability is ensured by a slow rate freezing process and storage at "
    "-80°C.",
    "To ensure sterility, samples from each lot are sent off to a third party testing facility. "
    "Each lot undergoes quarantine until the testing has been completed.",
    "When testing is complete, if the lot passes the rigorous testing phase and meets our "
    "internal release criteria, it moves from the quarantine stage and is eligible for sale.",
    "Sales are completed and shipped overnight to doctors and hospitals on dry ice to ensure "
    "preservation of the product.",
    "Individual product use is tracked internally by patient.",
]

RESEARCH = [
    ("We are proud to present a curated collection of published peer-reviewed studies. Majority "
     "of these studies are published personally by our esteemed scientific officers and members "
     "of our distinguished medical board team. These experts have contributed their extensive "
     "knowledge and expertise to the field of regenerative medicine, making significant "
     "advancements and breakthroughs."),
    ("We understand the importance of evidence-based research and its role in shaping the "
     "landscape of regenerative medicine. That's why we have compiled a list of our favorite "
     "publications that are both relevant and influential in this rapidly evolving field. These "
     "studies represent the cutting-edge discoveries and innovative approaches that are driving "
     "the future of regenerative medicine."),
    ("By exploring these publications, you have the opportunity to delve into the minds of these "
     "brilliant Ph.D. and MD authors who have dedicated their careers to advancing the boundaries "
     "of medical science. Their work encompasses a wide range of topics, from stem cell research "
     "to tissue engineering, from organ regeneration to gene therapies."),
]

# Pre-approved by legal. Reproduced exactly, character for character.
LEGAL = ("products are intended for cosmetic, research and/or homologous use products used "
         "and/or distributed by practitioner.The products are supplied aseptically and intended "
         "for single use. This product is intended for use by professionals only.")
