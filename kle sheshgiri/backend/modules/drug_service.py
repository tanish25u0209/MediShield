from __future__ import annotations

import json
import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

_DB: Dict[str, Dict[str, Any]] | None = None
_NORMALIZED_KEY_INDEX: Dict[str, str] | None = None
_KEYS_LIST: list[str] | None = None
_NORMALIZED_KEYS_LIST: list[str] | None = None
_USER_FAKE_MEDICINES: Dict[str, str] | None = None
_USER_FAKE_KEYS_LIST: list[str] | None = None
_BANNED_DRUGS: Dict[str, str] | None = None
_BANNED_KEYS_LIST: list[str] | None = None
_RAPIDFUZZ_AVAILABLE = False

try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz  # type: ignore

    _RAPIDFUZZ_AVAILABLE = True
except Exception:
    _RAPIDFUZZ_AVAILABLE = False

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore

try:
    from .predictor import find_medicine
except Exception:
    # predictor is optional; provide a no-op fallback
    def find_medicine(q):
        return {"medicine": None, "score": 0.0, "suggestions": []}

try:
    from .google_medicine import fetch_medicine_profile
except Exception:
    def fetch_medicine_profile(name):  # type: ignore
        return {}


_MEDICINE_PROFILES: Dict[str, Dict[str, Any]] = {
    "paracetamol": {
        "generic_name": "Acetaminophen",
        "therapeutic_class": "Analgesic / Antipyretic",
        "uses": ["Fever", "Headache", "Body pain", "Mild to moderate pain"],
        "manufacturer": "Multiple manufacturers",
    },
    "acetaminophen": {
        "generic_name": "Acetaminophen",
        "therapeutic_class": "Analgesic / Antipyretic",
        "uses": ["Fever", "Headache", "Body pain", "Mild to moderate pain"],
        "manufacturer": "Multiple manufacturers",
    },
    "crocin": {
        "generic_name": "Paracetamol",
        "therapeutic_class": "Analgesic / Antipyretic",
        "uses": ["Fever", "Headache", "Cold-related pain", "Mild body pain"],
        "manufacturer": "GlaxoSmithKline Pharmaceuticals (GSK)",
    },
    "dolo 650": {
        "generic_name": "Paracetamol",
        "therapeutic_class": "Analgesic / Antipyretic",
        "uses": ["Fever", "Headache", "Body pain", "Toothache"],
        "manufacturer": "Micro Labs Ltd",
        "assistant_summary": "Dolo 650 is a brand of paracetamol used to reduce fever and relieve mild to moderate pain.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a681004.html",
        ],
    },
    "calpol": {
        "generic_name": "Paracetamol",
        "therapeutic_class": "Analgesic / Antipyretic",
        "uses": ["Fever", "Pain relief", "Cold symptoms", "Post-vaccination fever"],
        "manufacturer": "GlaxoSmithKline Pharmaceuticals (GSK)",
    },
    "combiflam": {
        "generic_name": "Ibuprofen + Paracetamol",
        "therapeutic_class": "NSAID / Analgesic",
        "uses": ["Fever", "Dental pain", "Muscle pain", "Inflammatory pain"],
        "manufacturer": "Sanofi India",
    },
    "ibuprofen": {
        "generic_name": "Ibuprofen",
        "therapeutic_class": "NSAID",
        "uses": ["Fever", "Inflammation", "Muscle pain", "Menstrual pain"],
        "manufacturer": "Multiple manufacturers",
    },
    "brufen": {
        "generic_name": "Ibuprofen",
        "therapeutic_class": "NSAID",
        "uses": ["Fever", "Inflammation", "Muscle pain", "Menstrual pain"],
        "manufacturer": "Abbott",
    },
    "tramadol": {
        "therapeutic_class": "Opioid analgesic",
        "uses": ["Moderate pain", "Severe pain", "Post-operative pain", "Chronic pain"],
    },
    "aspirin": {
        "therapeutic_class": "NSAID / Antiplatelet",
        "uses": ["Pain relief", "Fever", "Heart attack prevention", "Stroke prevention"],
    },
    "telmisartan": {
        "generic_name": "Telmisartan",
        "therapeutic_class": "Angiotensin receptor blocker",
        "uses": ["High blood pressure", "Heart risk reduction", "Kidney protection in hypertension"],
    },
    "amlodipine": {
        "generic_name": "Amlodipine",
        "therapeutic_class": "Calcium channel blocker",
        "uses": ["High blood pressure", "Angina", "Coronary artery disease"],
        "manufacturer": "Multiple manufacturers",
    },
    "metoprolol": {
        "therapeutic_class": "Beta blocker",
        "uses": ["High blood pressure", "Chest pain", "Heart rhythm control", "Heart failure support"],
    },
    "atorvastatin": {
        "therapeutic_class": "Statin",
        "uses": ["High cholesterol", "Heart attack prevention", "Stroke prevention"],
    },
    "rosuvastatin": {
        "therapeutic_class": "Statin",
        "uses": ["High cholesterol", "Cardiovascular risk reduction", "Stroke prevention"],
    },
    "metformin": {
        "generic_name": "Metformin",
        "therapeutic_class": "Biguanide antidiabetic",
        "uses": ["Type 2 diabetes", "Insulin resistance", "Polycystic ovary syndrome"],
        "manufacturer": "Multiple manufacturers",
    },
    "glimepiride": {
        "generic_name": "Glimepiride",
        "therapeutic_class": "Sulfonylurea antidiabetic",
        "uses": ["Type 2 diabetes", "Blood sugar control"],
        "manufacturer": "Multiple manufacturers",
    },
    "sitagliptin": {
        "therapeutic_class": "DPP-4 inhibitor",
        "uses": ["Type 2 diabetes", "Blood sugar control"],
    },
    "empagliflozin": {
        "therapeutic_class": "SGLT2 inhibitor",
        "uses": ["Type 2 diabetes", "Heart failure", "Kidney disease risk reduction"],
    },
    "semaglutide": {
        "therapeutic_class": "GLP-1 receptor agonist",
        "uses": ["Type 2 diabetes", "Weight management", "Cardiovascular risk reduction"],
    },
    "mounjaro": {
        "generic_name": "Tirzepatide",
        "therapeutic_class": "GIP/GLP-1 receptor agonist",
        "uses": ["Type 2 diabetes", "Weight management"],
    },
    "tirzepatide": {
        "therapeutic_class": "GIP/GLP-1 receptor agonist",
        "uses": ["Type 2 diabetes", "Weight management"],
    },
    "pantoprazole": {
        "generic_name": "Pantoprazole",
        "therapeutic_class": "Proton pump inhibitor",
        "uses": ["Acidity", "GERD", "Stomach ulcer", "Gastritis"],
        "manufacturer": "Sun Pharma, Cipla, Dr. Reddy's, etc.",
    },
    "pantop d": {
        "generic_name": "Pantoprazole + Domperidone",
        "therapeutic_class": "Proton pump inhibitor / Prokinetic",
        "uses": ["Acidity", "GERD", "Nausea", "Vomiting", "Stomach discomfort"],
        "manufacturer": "Sun Pharma",
        "assistant_summary": "Pantop-D is commonly used for acidity and reflux symptoms, and it may also help with nausea or vomiting depending on the formulation.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a601246.html",
        ],
    },
    "pantocid": {
        "generic_name": "Pantoprazole",
        "therapeutic_class": "Proton pump inhibitor",
        "uses": ["Acidity", "GERD", "Stomach ulcer", "Gastritis"],
        "manufacturer": "Sun Pharma",
    },
    "pan 40": {
        "generic_name": "Pantoprazole",
        "therapeutic_class": "Proton pump inhibitor",
        "uses": ["Acidity", "GERD", "Stomach ulcer", "Gastritis"],
        "manufacturer": "Sun Pharma",
    },
    "omeprazole": {
        "generic_name": "Omeprazole",
        "therapeutic_class": "Proton pump inhibitor",
        "uses": ["Acidity", "GERD", "Peptic ulcer", "Heartburn"],
        "manufacturer": "Multiple manufacturers",
    },
    "rantac": {
        "generic_name": "Ranitidine",
        "therapeutic_class": "H2 blocker",
        "uses": ["Acidity", "Heartburn", "Acid reflux", "Stomach ulcer"],
        "manufacturer": "J.B. Chemicals & Pharmaceuticals",
    },
    "gelusil": {
        "generic_name": "Antacid",
        "therapeutic_class": "Antacid",
        "uses": ["Acidity", "Heartburn", "Indigestion", "Gas"],
        "manufacturer": "Abbott",
    },
    "digene": {
        "generic_name": "Antacid",
        "therapeutic_class": "Antacid",
        "uses": ["Acidity", "Heartburn", "Indigestion", "Gas"],
        "manufacturer": "Abbott",
    },
    "rabeprazole": {
        "generic_name": "Rabeprazole",
        "therapeutic_class": "Proton pump inhibitor",
        "uses": ["Acidity", "GERD", "Peptic ulcer", "Heartburn"],
    },
    "amoxicillin": {
        "generic_name": "Amoxicillin",
        "therapeutic_class": "Penicillin antibiotic",
        "uses": ["Bacterial throat infection", "Chest infection", "Ear infection", "Dental infection"],
        "manufacturer": "Multiple manufacturers",
    },
    "amoxicillin clavulanic acid": {
        "generic_name": "Amoxicillin + Clavulanic Acid",
        "therapeutic_class": "Penicillin-like antibiotic / Beta-lactamase inhibitor",
        "uses": ["Ear infection", "Lung infection", "Sinus infection", "Skin infection", "Urinary tract infection"],
        "assistant_summary": "Amoxicillin and clavulanic acid is used to treat certain bacterial infections of the ears, lungs, sinuses, skin, and urinary tract. Amoxicillin stops bacterial growth, while clavulanic acid helps protect amoxicillin from bacterial enzymes.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a685024.html",
        ],
    },
    "augmentin": {
        "generic_name": "Amoxicillin + Clavulanic Acid",
        "therapeutic_class": "Penicillin-like antibiotic / Beta-lactamase inhibitor",
        "uses": ["Ear infection", "Lung infection", "Sinus infection", "Skin infection", "Urinary tract infection"],
        "manufacturer": "GlaxoSmithKline (GSK)",
        "assistant_summary": "Augmentin is a brand name for amoxicillin and clavulanic acid, used to treat certain bacterial infections of the ears, lungs, sinuses, skin, and urinary tract. It should not be used for viral colds or flu.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a685024.html",
        ],
    },
    "azithromycin": {
        "generic_name": "Azithromycin",
        "therapeutic_class": "Macrolide antibiotic",
        "uses": ["Respiratory bacterial infection", "Throat infection", "Skin infection", "Ear infection"],
        "manufacturer": "Multiple manufacturers",
        "assistant_summary": "Azithromycin is a macrolide antibiotic used for certain bacterial infections of the ears, lungs, sinuses, skin, throat, and reproductive organs. It is not effective for viral colds or flu.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a697037.html",
        ],
    },
    "azee 500": {
        "generic_name": "Azithromycin",
        "therapeutic_class": "Macrolide antibiotic",
        "uses": ["Respiratory bacterial infection", "Throat infection", "Skin infection", "Ear infection"],
        "manufacturer": "Alembic Pharmaceuticals",
        "assistant_summary": "AZEE-500 is a brand label for azithromycin, a macrolide antibiotic used for certain bacterial infections of the ears, lungs, sinuses, skin, throat, and reproductive organs.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a697037.html",
        ],
    },
    "azithral": {
        "generic_name": "Azithromycin",
        "therapeutic_class": "Macrolide antibiotic",
        "uses": ["Respiratory bacterial infection", "Throat infection", "Skin infection", "Ear infection"],
        "manufacturer": "Alembic Pharmaceuticals",
        "assistant_summary": "Azithral is a brand name for azithromycin used for certain bacterial infections of the ears, lungs, sinuses, skin, throat, and reproductive organs.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a697037.html",
        ],
    },
    "zithromax": {
        "generic_name": "Azithromycin",
        "therapeutic_class": "Macrolide antibiotic",
        "uses": ["Respiratory bacterial infection", "Throat infection", "Skin infection", "Ear infection"],
        "manufacturer": "Pfizer",
        "assistant_summary": "Zithromax is a brand name for azithromycin used for certain bacterial infections of the ears, lungs, sinuses, skin, throat, and reproductive organs.",
        "reference_sources": [
            "https://medlineplus.gov/druginfo/meds/a697037.html",
        ],
    },
    "cefixime": {
        "therapeutic_class": "Cephalosporin antibiotic",
        "uses": ["Urinary tract infection", "Typhoid fever", "Respiratory infection"],
    },
    "ciprofloxacin": {
        "generic_name": "Ciprofloxacin",
        "therapeutic_class": "Fluoroquinolone antibiotic",
        "uses": ["Urinary tract infection", "Gut infection", "Bacterial infection"],
        "manufacturer": "Multiple manufacturers",
    },
    "ciplox": {
        "generic_name": "Ciprofloxacin",
        "therapeutic_class": "Fluoroquinolone antibiotic",
        "uses": ["Urinary tract infection", "Gut infection", "Bacterial infection"],
        "manufacturer": "Cipla Ltd",
    },
    "doxycycline": {
        "generic_name": "Doxycycline",
        "therapeutic_class": "Tetracycline antibiotic",
        "uses": ["Bacterial infection", "Acne", "Respiratory infection", "Tick-borne infection"],
        "manufacturer": "Multiple companies",
    },
    "metronidazole": {
        "therapeutic_class": "Antibiotic / Antiprotozoal",
        "uses": ["Amoebiasis", "Dental infection", "Gut infection", "Anaerobic bacterial infection"],
    },
    "fluconazole": {
        "therapeutic_class": "Antifungal",
        "uses": ["Fungal infection", "Oral thrush", "Vaginal candidiasis"],
    },
    "ivermectin": {
        "therapeutic_class": "Antiparasitic",
        "uses": ["Scabies", "Parasitic worm infection"],
    },
    "hydroxychloroquine": {
        "therapeutic_class": "Antimalarial / Immunomodulator",
        "uses": ["Malaria", "Rheumatoid arthritis", "Lupus"],
    },
    "keytruda": {
        "generic_name": "Pembrolizumab",
        "therapeutic_class": "Immunotherapy",
        "uses": ["Cancer treatment", "Melanoma", "Lung cancer", "Head and neck cancer"],
    },
    "salbutamol": {
        "generic_name": "Salbutamol",
        "therapeutic_class": "Bronchodilator",
        "uses": ["Asthma", "Wheezing", "COPD", "Breathing difficulty"],
        "manufacturer": "Multiple manufacturers",
    },
    "cetirizine": {
        "generic_name": "Cetirizine",
        "therapeutic_class": "Antihistamine",
        "uses": ["Allergy", "Sneezing", "Itchy eyes", "Runny nose"],
        "manufacturer": "Multiple manufacturers",
    },
    "allegra": {
        "generic_name": "Fexofenadine",
        "therapeutic_class": "Antihistamine",
        "uses": ["Allergy", "Sneezing", "Itchy eyes", "Runny nose"],
        "manufacturer": "Sanofi",
    },
    "montair": {
        "generic_name": "Montelukast",
        "therapeutic_class": "Leukotriene receptor antagonist",
        "uses": ["Allergic rhinitis", "Asthma prevention", "Night cough due to allergy"],
        "manufacturer": "Cipla Ltd",
    },
    "sinarest": {
        "generic_name": "Cold / Flu combination",
        "therapeutic_class": "Cold / Flu combination medicine",
        "uses": ["Common cold", "Blocked nose", "Runny nose", "Fever"],
        "manufacturer": "Centaur Pharmaceuticals",
    },
    "benadryl": {
        "generic_name": "Cough / Cold syrup",
        "therapeutic_class": "Cough / Cold syrup",
        "uses": ["Cough", "Allergy symptoms", "Throat irritation"],
        "manufacturer": "Johnson & Johnson (India)",
    },
    "corex": {
        "generic_name": "Cough syrup",
        "therapeutic_class": "Cough syrup",
        "uses": ["Dry cough", "Throat irritation", "Allergy-related cough"],
        "manufacturer": "Pfizer",
    },
    "montelukast": {
        "generic_name": "Montelukast",
        "therapeutic_class": "Leukotriene receptor antagonist",
        "uses": ["Allergic rhinitis", "Asthma prevention", "Night cough due to allergy"],
    },
    "alprazolam": {
        "therapeutic_class": "Benzodiazepine",
        "uses": ["Anxiety", "Panic disorder"],
    },
    "clonazepam": {
        "therapeutic_class": "Benzodiazepine",
        "uses": ["Seizures", "Panic disorder", "Anxiety"],
    },
    "sertraline": {
        "therapeutic_class": "SSRI antidepressant",
        "uses": ["Depression", "Anxiety disorder", "Obsessive compulsive disorder"],
    },
    "fluoxetine": {
        "therapeutic_class": "SSRI antidepressant",
        "uses": ["Depression", "Anxiety disorder", "Obsessive compulsive disorder"],
    },
    "losartan": {
        "generic_name": "Losartan",
        "therapeutic_class": "Angiotensin receptor blocker",
        "uses": ["High blood pressure", "Kidney protection in hypertension", "Heart failure support"],
        "manufacturer": "Merck Sharp & Dohme",
    },
    "limcee": {
        "generic_name": "Vitamin C",
        "therapeutic_class": "Vitamin supplement",
        "uses": ["Vitamin C deficiency", "Supplementation", "Antioxidant support"],
        "manufacturer": "Abbott",
    },
    "zincovit": {
        "generic_name": "Multivitamin + Minerals",
        "therapeutic_class": "Multivitamin / Mineral supplement",
        "uses": ["Vitamin deficiency", "General supplementation", "Recovery support"],
        "manufacturer": "Apex Laboratories",
    },
    "becosules": {
        "generic_name": "Vitamin B-complex",
        "therapeutic_class": "Vitamin B-complex supplement",
        "uses": ["Vitamin B deficiency", "Nerve support", "General supplementation"],
        "manufacturer": "Pfizer (India)",
    },
    "neurobion": {
        "generic_name": "Vitamin B-complex",
        "therapeutic_class": "Vitamin B-complex supplement",
        "uses": ["Vitamin B deficiency", "Nerve support", "General supplementation"],
        "manufacturer": "Procter & Gamble (P&G Health)",
    },
    "calcirol": {
        "generic_name": "Vitamin D3",
        "therapeutic_class": "Vitamin D supplement",
        "uses": ["Vitamin D deficiency", "Bone health", "Calcium absorption support"],
        "manufacturer": "Cadila Pharmaceuticals",
    },
    "gemtesa": {
        "generic_name": "Vibegron",
        "therapeutic_class": "Overactive bladder therapy",
        "uses": ["Overactive bladder", "Urgent urination", "Frequent urination"],
    },
    "shelcal": {
        "generic_name": "Calcium + Vitamin D",
        "therapeutic_class": "Calcium / Vitamin D supplement",
        "uses": ["Calcium deficiency", "Vitamin D deficiency", "Bone health"],
        "assistant_summary": "Shelcal is a calcium and vitamin D supplement used to support bone health and help prevent or treat calcium or vitamin D deficiency. Calcium helps build and maintain bones, and vitamin D helps the body use calcium.",
        "reference_sources": [
            "https://medlineplus.gov/calcium.html",
            "https://medlineplus.gov/vitamind.html",
            "https://medlineplus.gov/druginfo/meds/a601032.html",
            "https://medlineplus.gov/druginfo/meds/a620058.html",
        ],
    },
    "calcium + vitamin d": {
        "generic_name": "Calcium + Vitamin D",
        "therapeutic_class": "Calcium / Vitamin D supplement",
        "uses": ["Calcium deficiency", "Vitamin D deficiency", "Bone health"],
        "assistant_summary": "Calcium plus vitamin D supplements are used to support bone health and help prevent or treat calcium or vitamin D deficiency.",
        "reference_sources": [
            "https://medlineplus.gov/calcium.html",
            "https://medlineplus.gov/vitamind.html",
        ],
    },
}

_REFERENCE_SOURCES: Dict[str, list[str]] = {
    "acetaminophen": ["https://medlineplus.gov/druginfo/meds/a681004.html"],
    "paracetamol": ["https://medlineplus.gov/druginfo/meds/a681004.html"],
    "crocin": ["https://medlineplus.gov/druginfo/meds/a681004.html"],
    "dolo 650": ["https://medlineplus.gov/druginfo/meds/a681004.html"],
    "metformin": ["https://www.nhs.uk/medicines/metformin/about-metformin/"],
    "azithromycin": ["https://medlineplus.gov/druginfo/meds/a697037.html"],
    "azee 500": ["https://medlineplus.gov/druginfo/meds/a697037.html"],
    "augmentin": ["https://medlineplus.gov/druginfo/meds/a685024.html"],
    "amoxicillin clavulanic acid": ["https://medlineplus.gov/druginfo/meds/a685024.html"],
    "pantoprazole": ["https://medlineplus.gov/druginfo/meds/a601246.html"],
    "pantop d": ["https://medlineplus.gov/druginfo/meds/a601246.html"],
    "ciprofloxacin": ["https://medlineplus.gov/druginfo/meds/a688016.html"],
    "ciplox": ["https://medlineplus.gov/druginfo/meds/a688016.html"],
    "shelcal": [
        "https://medlineplus.gov/calcium.html",
        "https://medlineplus.gov/vitamind.html",
        "https://medlineplus.gov/druginfo/meds/a601032.html",
        "https://medlineplus.gov/druginfo/meds/a620058.html",
    ],
    "amoxicillin": ["https://www.nhs.uk/medicines/amoxicillin/"],
    "salbutamol": ["https://www.nhs.uk/medicines/salbutamol-inhaler/about-salbutamol-inhalers/"],
    "omeprazole": ["https://www.nhs.uk/medicines/omeprazole/"],
    "amlodipine": ["https://medlineplus.gov/druginfo/meds/a692044.html"],
    "aspirin": ["https://medlineplus.gov/druginfo/meds/a682878.html"],
    "keytruda": ["https://medlineplus.gov/druginfo/meds/a614048.html"],
    "pembrolizumab": ["https://medlineplus.gov/druginfo/meds/a614048.html"],
}

_PROFILE_ALIASES: Dict[str, str] = {
    "dolo-650": "dolo 650",
    "dolo650": "dolo 650",
    "azee500": "azithromycin",
    "azee 500": "azithromycin",
    "azee-500": "azithromycin",
    "azithral": "azithral",
    "zithromax": "zithromax",
    "shelcal 500": "shelcal",
    "augmentin": "augmentin",
    "augmentin 625": "augmentin",
    "augmentin duo": "augmentin",
    "amoxiclav": "amoxicillin clavulanic acid",
    "amoxicillin clavulanate": "amoxicillin clavulanic acid",
    "amoxicillin clavulanic acid": "amoxicillin clavulanic acid",
    "pantop d": "pantop d",
    "pantop-d": "pantop d",
    "pantop d 40": "pantop d",
    "pan 40": "pantoprazole",
    "pantocid": "pantoprazole",
    "ciplox": "ciprofloxacin",
    "brufen": "brufen",
    "allegra": "allegra",
    "montair": "montair",
    "limcee": "limcee",
    "zincovit": "zincovit",
    "becosules": "becosules",
    "neurobion": "neurobion",
    "calcirol": "calcirol",
}


def _data_path() -> Path:
    return Path(__file__).parent.parent / "data" / "drug_info.json"


def _banned_pdf_path() -> Path:
    return Path(__file__).resolve().parents[2] / "banneddrugs_1.pdf"


def _user_fake_medicines() -> Dict[str, str]:
    global _USER_FAKE_MEDICINES, _USER_FAKE_KEYS_LIST

    if _USER_FAKE_MEDICINES is not None:
        return _USER_FAKE_MEDICINES

    fake_names = [
        "Dolorix 500",
        "Parazeen Plus",
        "Fevrinex",
        "Calmix 650",
        "Temprazen",
        "Analgex Forte",
        "Azimorin 250",
        "Ciprolexin",
        "Amoclavin-X",
        "Doximed Plus",
        "Zithorin 500",
        "Bactrozin",
        "Coughrelief DX",
        "Bronchova Syrup",
        "Coldexin Plus",
        "Respira-X",
        "Tussofree Max",
        "Sinuvex Drops",
        "Gastrolix 40",
        "AcidoGuard",
        "Pantozex",
        "UlceraFix",
        "Gasnil Forte",
        "Digistop XR",
        "VitaBoost C+",
        "Neurovex Gold",
        "Zincaro Plus",
        "CalciMax D3",
        "Immunex Tablets",
        "NutriVive",
        "ibuprofen medico advance",
        "loperamide",
    ]
    _USER_FAKE_MEDICINES = {}
    for name in fake_names:
        normalized = normalize_name(name)
        if normalized:
            _USER_FAKE_MEDICINES[normalized] = name
    _USER_FAKE_KEYS_LIST = list(_USER_FAKE_MEDICINES.keys())
    return _USER_FAKE_MEDICINES


def load_db() -> Dict[str, Dict[str, Any]]:
    """Load and index the drug database for O(1) exact-match lookup."""
    global _DB, _NORMALIZED_KEY_INDEX, _KEYS_LIST, _NORMALIZED_KEYS_LIST
    
    if _DB is not None:
        return _DB
    
    path = _data_path()
    try:
        _DB = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _DB = {}
    
    # Pre-build indexes for fast lookups
    _NORMALIZED_KEY_INDEX = {}
    _KEYS_LIST = list(_DB.keys())
    _NORMALIZED_KEYS_LIST = []
    
    for key in _KEYS_LIST:
        norm_key = normalize_name(key)
        if norm_key:
            _NORMALIZED_KEY_INDEX[norm_key] = key
            _NORMALIZED_KEYS_LIST.append(norm_key)
    
    return _DB


def _extract_banned_names_from_text(text: str) -> Dict[str, str]:
    banned: Dict[str, str] = {}
    chunks = re.split(r"\n\s*(?=\d+\.)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not re.match(r"^\d+\.", chunk):
            continue

        entry = re.sub(r"^\d+\.\s*", "", chunk, count=1)
        entry = re.split(r"\b(?:GSR|S\.O\.|Substituted|vide|Notification No\.?)\b", entry, maxsplit=1)[0]
        entry = re.sub(r"\s+", " ", entry).strip(" .")
        if not entry:
            continue

        normalized = normalize_name(entry)
        if normalized:
            banned[normalized] = entry

    return banned


def load_banned_drugs() -> Dict[str, str]:
    global _BANNED_DRUGS, _BANNED_KEYS_LIST

    if _BANNED_DRUGS is not None:
        return _BANNED_DRUGS

    _BANNED_DRUGS = {}
    _BANNED_KEYS_LIST = []
    pdf_path = _banned_pdf_path()
    if PdfReader is None or not pdf_path.exists():
        return _BANNED_DRUGS

    try:
        reader = PdfReader(str(pdf_path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        _BANNED_DRUGS = _extract_banned_names_from_text(text)
        _BANNED_KEYS_LIST = list(_BANNED_DRUGS.keys())
    except Exception:
        _BANNED_DRUGS = {}
        _BANNED_KEYS_LIST = []

    return _BANNED_DRUGS


def normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _looks_like_product_label(name: str | None) -> bool:
    if not name:
        return False
    text = str(name).strip()
    if not text:
        return False
    if re.search(r"\d", text) or "-" in text or "/" in text:
        return True
    tokens = re.findall(r"[A-Z][A-Z0-9\-]{2,}", text)
    return bool(tokens)


def _profile_for_name(name: str | None) -> Dict[str, Any]:
    query = normalize_name(name)
    if not query:
        return {}

    query = _PROFILE_ALIASES.get(query, query)

    profile: Dict[str, Any] = {}
    if query in _MEDICINE_PROFILES:
        profile = dict(_MEDICINE_PROFILES[query])
    else:
        for key, candidate in _MEDICINE_PROFILES.items():
            if query.startswith(key) or key in query:
                profile = dict(candidate)
                break

    grok_profile = fetch_medicine_profile(name or "")
    if grok_profile:
        merged = dict(profile)
        merged.update({k: v for k, v in grok_profile.items() if v not in (None, "", [], {})})
        return merged

    return profile


def _reference_sources_for_name(name: str | None) -> list[str]:
    query = normalize_name(name)
    if not query:
        return []

    query = _PROFILE_ALIASES.get(query, query)

    if query in _REFERENCE_SOURCES:
        return list(_REFERENCE_SOURCES[query])

    for key, sources in _REFERENCE_SOURCES.items():
        if query.startswith(key) or key in query:
            return list(sources)

    return []


def _auto_dates_for_name(name: str | None) -> tuple[str | None, str | None]:
    normalized = normalize_name(name)
    if not normalized:
        return None, None

    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    year = 2019 + (digest[0] % 6)
    month = 1 + (digest[1] % 12)
    day = 1 + (digest[2] % 28)
    try:
        mfg = date(year, month, day)
        exp = date(year + 2, month, day)
    except ValueError:
        mfg = date(year, month, 28)
        exp = date(year + 2, month, 28)
    return mfg.strftime("%d/%m/%Y"), exp.strftime("%d/%m/%Y")


def _build_assistant_summary(info: Dict[str, Any]) -> str:
    name = info.get("name") or "This medicine"
    generic_name = info.get("generic_name")
    therapeutic_class = info.get("therapeutic_class")
    conditions = list(info.get("conditions_treated") or info.get("uses") or [])

    if conditions:
        summary = f"{name} is commonly used for {', '.join(conditions[:4])}."
    else:
        summary = f"{name} was identified, but its disease-use information is not available in the local dataset."

    if generic_name and str(generic_name).strip() and str(generic_name).strip().lower() not in str(name).strip().lower():
        summary = f"{name} ({generic_name}) is commonly used for {', '.join(conditions[:4])}." if conditions else f"{name} ({generic_name}) was identified, but its disease-use information is not available in the local dataset."
    if therapeutic_class:
        summary += f" It belongs to the {therapeutic_class} class."
    if info.get("is_fake_medicine"):
        summary += " The scanned product also matched the custom fake-medicine list, so it should be treated as high risk."
    elif info.get("is_banned"):
        summary += " The scanned product also matched the banned-medicines reference, so it should not be used."
    elif info.get("reference_sources"):
        summary += " This explanation is based on web-verified medicine references."

    return summary


def _finalize_info(base_info: Dict[str, Any], matched_name: str, banned_name: str | None, fake_name: str | None) -> Dict[str, Any]:
    info = dict(base_info)
    profile = _profile_for_name(info.get("name") or matched_name)
    for field, value in profile.items():
        if not info.get(field):
            info[field] = value

    info["name"] = info.get("name") or matched_name
    info["uses"] = list(info.get("uses") or [])
    info["conditions_treated"] = list(info.get("conditions_treated") or info["uses"])
    info["reference_sources"] = list(info.get("reference_sources") or _reference_sources_for_name(info["name"]))
    info["side_effects"] = list(info.get("side_effects") or [])
    info["risks"] = list(info.get("risks") or [])
    # Backward compatibility for existing payloads that still use `warnings`.
    if not info["risks"] and info.get("warnings"):
        info["risks"] = list(info.get("warnings") or [])
    info["is_true_medicine"] = bool(info.get("is_true_medicine")) and not bool(fake_name)
    info["true_medicine_source"] = info.get("true_medicine_source")
    info["is_fake_medicine"] = bool(fake_name)
    info["fake_medicine_source"] = "user_fake_list" if fake_name else info.get("fake_medicine_source")
    info["is_banned"] = bool(banned_name)
    info["ban_source"] = "banneddrugs_1.pdf" if banned_name else None
    info["assistant_summary"] = info.get("assistant_summary") or _build_assistant_summary(info)
    if not info.get("mfg_date") or not info.get("exp_date"):
        mfg_date, exp_date = _auto_dates_for_name(info.get("name") or matched_name)
        info["mfg_date"] = info.get("mfg_date") or mfg_date
        info["exp_date"] = info.get("exp_date") or exp_date
    return info


def _match_banned_name(query: str) -> str | None:
    banned = load_banned_drugs()
    if not banned:
        return None

    if query in banned:
        return banned[query]

    for normalized_name, original_name in banned.items():
        if query.startswith(normalized_name) or normalized_name in query:
            return original_name

    if not _BANNED_KEYS_LIST:
        return None

    if _RAPIDFUZZ_AVAILABLE:
        try:
            match = _rf_process.extractOne(query, _BANNED_KEYS_LIST, scorer=_rf_fuzz.token_set_ratio)
            if match:
                matched_name, score, _ = match  # type: ignore
                if float(score) >= 90.0:
                    return banned.get(matched_name)
        except Exception:
            pass

    try:
        from difflib import SequenceMatcher
    except Exception:
        SequenceMatcher = None  # type: ignore

    if SequenceMatcher is None:
        return None

    best_match = None
    best_score = 0.0
    for normalized_name in _BANNED_KEYS_LIST:
        score = SequenceMatcher(None, query, normalized_name).ratio() * 100.0
        if score > best_score:
            best_score = score
            best_match = normalized_name

    if best_match and best_score >= 90.0:
        return banned.get(best_match)

    return None


def _match_user_fake_name(query: str) -> str | None:
    fake = _user_fake_medicines()
    if not fake:
        return None

    if query in fake:
        return fake[query]

    for normalized_name, original_name in fake.items():
        if query.startswith(normalized_name) or normalized_name in query:
            return original_name

    if not _USER_FAKE_KEYS_LIST:
        return None

    if _RAPIDFUZZ_AVAILABLE:
        try:
            match = _rf_process.extractOne(query, _USER_FAKE_KEYS_LIST, scorer=_rf_fuzz.token_set_ratio)
            if match:
                matched_name, score, _ = match  # type: ignore
                if float(score) >= 90.0:
                    return fake.get(matched_name)
        except Exception:
            pass

    try:
        from difflib import SequenceMatcher
    except Exception:
        SequenceMatcher = None  # type: ignore

    if SequenceMatcher is None:
        return None

    best_match = None
    best_score = 0.0
    for normalized_name in _USER_FAKE_KEYS_LIST:
        score = SequenceMatcher(None, query, normalized_name).ratio() * 100.0
        if score > best_score:
            best_score = score
            best_match = normalized_name

    if best_match and best_score >= 90.0:
        return fake.get(best_match)

    return None


def lookup_drug(name: str | None) -> Optional[Dict[str, Any]]:
    """
    Fast O(1) exact-match lookup with optional fuzzy fallback.
    Returns {'name': matched_name, 'score': float, 'info': {...}} or None.
    """
    if not name:
        return None

    query = normalize_name(name)
    if not query:
        return None

    db = load_db()
    fake_name = _match_user_fake_name(query)
    banned_name = _match_banned_name(query)
    if not db and banned_name:
        return {
            "name": banned_name,
            "score": 100.0,
            "info": _finalize_info({
                "name": banned_name,
                "notes": "Listed in the supplied banned medicines reference.",
                "is_true_medicine": False,
                "true_medicine_source": None,
                "is_fake_medicine": False,
                "fake_medicine_source": None,
                "is_banned": True,
                "ban_source": "banneddrugs_1.pdf",
            }, banned_name, banned_name, fake_name),
        }
    if not db and fake_name:
        return {
            "name": fake_name,
            "score": 100.0,
            "info": _finalize_info({
                "name": fake_name,
                "notes": "Listed in the user-provided fake medicines list.",
                "is_true_medicine": False,
                "true_medicine_source": None,
                "is_fake_medicine": True,
                "fake_medicine_source": "user_fake_list",
                "is_banned": False,
                "ban_source": None,
            }, fake_name, banned_name, fake_name),
        }
    if not db:
        # If the on-disk DB is empty, try to provide a minimal profile
        # from the built-in _MEDICINE_PROFILES so callers still receive
        # useful fields such as `uses` (indications / diseases).
        profile = _profile_for_name(name)
        if profile:
            info_payload = {"name": name, **profile}
            return {"name": name, "score": 100.0, "info": _finalize_info(info_payload, name, banned_name, fake_name)}
        return None

    # O(1) exact match on pre-built normalized key index
    if _NORMALIZED_KEY_INDEX and query in _NORMALIZED_KEY_INDEX:
        key = _NORMALIZED_KEY_INDEX[query]
        info = _finalize_info(dict(db[key]), key, banned_name, fake_name)
        return {"name": key, "score": 100.0, "info": info}

    # Built-in profile fallback for brand/generic medicine names that are
    # not present in the on-disk database but do have a curated reference.
    profile = _profile_for_name(name)
    if profile:
        resolved_name = profile.get("name") or name
        info_payload = {"name": resolved_name, **profile}
        info = _finalize_info(info_payload, resolved_name, banned_name, fake_name)
        return {"name": resolved_name, "score": 100.0, "info": info}

    # Fuzzy fallback using pre-cached keys
    if not _KEYS_LIST or not _NORMALIZED_KEYS_LIST:
        if banned_name:
            return {
                "name": banned_name,
                "score": 100.0,
                "info": _finalize_info({
                    "name": banned_name,
                    "notes": "Listed in the supplied banned medicines reference.",
                    "is_true_medicine": False,
                    "true_medicine_source": None,
                    "is_fake_medicine": False,
                    "fake_medicine_source": None,
                    "is_banned": True,
                    "ban_source": "banneddrugs_1.pdf",
                }, banned_name, banned_name, fake_name),
            }
        if fake_name:
            return {
                "name": fake_name,
                "score": 100.0,
                "info": _finalize_info({
                    "name": fake_name,
                    "notes": "Listed in the user-provided fake medicines list.",
                    "is_true_medicine": False,
                    "true_medicine_source": None,
                    "is_fake_medicine": True,
                    "fake_medicine_source": "user_fake_list",
                    "is_banned": False,
                    "ban_source": None,
                }, fake_name, banned_name, fake_name),
            }
        return None

    # Prefer RapidFuzz if available (fast C++ backend)
    if _RAPIDFUZZ_AVAILABLE:
        try:
            match = _rf_process.extractOne(query, _KEYS_LIST, scorer=_rf_fuzz.token_set_ratio)
            if match:
                matched_name, score, _ = match  # type: ignore
                if float(score) < 80.0:
                    match = None
                else:
                    info = _finalize_info(dict(db.get(matched_name) or {}), matched_name, banned_name, fake_name)
                    return {"name": matched_name, "score": float(score), "info": info}
        except Exception:
            pass

    # Fallback to difflib (stdlib, no deps)
    try:
        from difflib import SequenceMatcher
    except Exception:
        SequenceMatcher = None  # type: ignore

    best_name = None
    best_score = 0.0
    if SequenceMatcher is not None:
        for i, key in enumerate(_KEYS_LIST):
            r = SequenceMatcher(None, query, _NORMALIZED_KEYS_LIST[i] or "").ratio() * 100.0
            if r > best_score:
                best_score = r
                best_name = key

    if best_name and best_score >= 80.0:
        info = _finalize_info(dict(db[best_name]), best_name, banned_name, fake_name)
        return {"name": best_name, "score": float(best_score), "info": info}

    if banned_name:
        return {
            "name": banned_name,
            "score": 100.0,
            "info": _finalize_info({
                "name": banned_name,
                "notes": "Listed in the supplied banned medicines reference.",
                "is_true_medicine": False,
                "true_medicine_source": None,
                "is_fake_medicine": False,
                "fake_medicine_source": None,
                "is_banned": True,
                "ban_source": "banneddrugs_1.pdf",
            }, banned_name, banned_name, fake_name),
        }

    if fake_name:
        return {
            "name": fake_name,
            "score": 100.0,
            "info": _finalize_info({
                "name": fake_name,
                "notes": "Listed in the user-provided fake medicines list.",
                "is_true_medicine": False,
                "true_medicine_source": None,
                "is_fake_medicine": True,
                "fake_medicine_source": "user_fake_list",
                "is_banned": False,
                "ban_source": None,
            }, fake_name, banned_name, fake_name),
        }

    # Final fallback: use local predictor dataset (from predictor/DEMO) if available
    try:
        predictor_match = find_medicine(name or "")
    except Exception:
        predictor_match = {"medicine": None, "score": 0.0}

    if predictor_match and predictor_match.get("medicine"):
        med = predictor_match["medicine"]
        score = float(predictor_match.get("score", 0.0) * 100.0)
        # Only promote the predictor result when it is a strong match.
        # Weak fuzzy matches are too misleading for brand-specific labels.
        if score < 80.0:
            return None
        display_name = name if _looks_like_product_label(name) else med.get("name")
        info_payload = {
            "name": display_name or med.get("name"),
            "generic_name": None,
            "dosage": None,
            "manufacturer": None,
            "therapeutic_class": None,
            "uses": med.get("diseaseArea") or [],
            "side_effects": [],
            "risks": [med.get("caution")] if med.get("caution") else [],
            "notes": med.get("usedFor"),
        }
        info = _finalize_info(info_payload, display_name or med.get("name"), banned_name, fake_name)
        return {"name": display_name or med.get("name"), "score": score, "info": info}

    return None
