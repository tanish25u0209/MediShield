from modules.drug_service import lookup_drug

for name in ["Metformin", "Paracetamol", "Dolo 650", "UnknownMed"]:
    res = lookup_drug(name)
    print(name, "->", res and res.get('info') and res['info'].get('uses'))
