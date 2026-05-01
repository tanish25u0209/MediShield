const medicines = [
  {
    name: "Paracetamol",
    aliases: ["acetaminophen", "dolo", "calpol", "crocin"],
    usedFor: "Fever and mild to moderate pain such as headache, body ache, toothache, or muscle pain.",
    diseaseArea: ["Fever", "Pain relief"],
    caution: "Avoid taking multiple products that contain paracetamol. Too much can seriously harm the liver.",
  },
  {
    name: "Ibuprofen",
    aliases: ["brufen", "advil", "motrin"],
    usedFor: "Pain, swelling, menstrual cramps, dental pain, muscle pain, and fever.",
    diseaseArea: ["Inflammation", "Pain", "Fever"],
    caution: "May irritate the stomach and may not be suitable for kidney disease, ulcers, blood thinners, or late pregnancy.",
  },
  {
    name: "Amoxicillin",
    aliases: ["amoxil", "mox", "amoxycillin"],
    usedFor: "Bacterial infections such as some throat, ear, sinus, chest, dental, skin, and urinary infections.",
    diseaseArea: ["Bacterial infection"],
    caution: "Antibiotics should be used only when prescribed. They do not treat viral colds or flu.",
  },
  {
    name: "Azithromycin",
    aliases: ["azee", "zithromax", "azithral"],
    usedFor: "Certain bacterial respiratory, throat, skin, and sexually transmitted infections.",
    diseaseArea: ["Bacterial infection"],
    caution: "Use only with medical advice. It can interact with heart rhythm medicines and is not for viral illness.",
  },
  {
    name: "Cetirizine",
    aliases: ["zyrtec", "cetzine", "alerid"],
    usedFor: "Allergy symptoms such as sneezing, runny nose, itchy eyes, hives, and skin itching.",
    diseaseArea: ["Allergy"],
    caution: "Can cause sleepiness in some people. Be careful with driving or alcohol.",
  },
  {
    name: "Loratadine",
    aliases: ["claritin", "lorfast"],
    usedFor: "Allergic rhinitis, sneezing, watery eyes, and hives.",
    diseaseArea: ["Allergy"],
    caution: "Usually less sedating, but check with a clinician if pregnant, breastfeeding, or using other medicines.",
  },
  {
    name: "Metformin",
    aliases: ["glycomet", "glucophage"],
    usedFor: "Type 2 diabetes, usually to help lower blood sugar and improve insulin sensitivity.",
    diseaseArea: ["Type 2 diabetes"],
    caution: "Needs medical monitoring, especially with kidney disease or dehydration.",
  },
  {
    name: "Amlodipine",
    aliases: ["amlopres", "norvasc"],
    usedFor: "High blood pressure and some types of chest pain called angina.",
    diseaseArea: ["Hypertension", "Angina"],
    caution: "Do not stop blood pressure medicines suddenly without medical advice.",
  },
  {
    name: "Atorvastatin",
    aliases: ["lipitor", "atorva"],
    usedFor: "High cholesterol and reducing the risk of heart attack or stroke in selected patients.",
    diseaseArea: ["High cholesterol", "Heart risk reduction"],
    caution: "Report unexplained severe muscle pain or weakness to a clinician.",
  },
  {
    name: "Omeprazole",
    aliases: ["omez", "prilosec"],
    usedFor: "Acidity, acid reflux, heartburn, stomach ulcers, and gastroesophageal reflux disease.",
    diseaseArea: ["Acid reflux", "Ulcer disease"],
    caution: "Frequent or long-term use should be reviewed by a clinician.",
  },
  {
    name: "Pantoprazole",
    aliases: ["pantocid", "protonix", "pan"],
    usedFor: "Acid reflux, heartburn, gastritis, and stomach ulcer protection in selected cases.",
    diseaseArea: ["Acid reflux", "Gastritis"],
    caution: "Persistent stomach pain, vomiting blood, black stools, or weight loss needs urgent medical care.",
  },
  {
    name: "Salbutamol",
    aliases: ["albuterol", "asthalin", "ventolin"],
    usedFor: "Quick relief of wheezing, breathlessness, or chest tightness in asthma or COPD.",
    diseaseArea: ["Asthma", "COPD symptoms"],
    caution: "Needing it very often can mean asthma is not controlled. Seek medical review.",
  },
  {
    name: "Montelukast",
    aliases: ["montair", "singulair"],
    usedFor: "Asthma prevention and allergy-related nasal symptoms in selected patients.",
    diseaseArea: ["Asthma", "Allergic rhinitis"],
    caution: "Mood, sleep, or behavior changes should be discussed with a clinician promptly.",
  },
  {
    name: "Aspirin",
    aliases: ["ecosprin", "disprin"],
    usedFor: "Pain and fever in some doses; low-dose aspirin is used for heart and stroke prevention in selected patients.",
    diseaseArea: ["Pain", "Fever", "Clot prevention"],
    caution: "Can increase bleeding risk. Do not use for children with viral illness unless specifically prescribed.",
  },
  {
    name: "Domperidone",
    aliases: ["domstal"],
    usedFor: "Nausea, vomiting, and stomach motility symptoms in selected cases.",
    diseaseArea: ["Nausea", "Vomiting"],
    caution: "May not be suitable for people with certain heart rhythm problems or liver disease.",
  },
];

const form = document.querySelector("#medicine-form");
const input = document.querySelector("#medicine-input");
const resultCard = document.querySelector("#result-card");
const exampleList = document.querySelector("#example-list");
const detectButton = document.querySelector("#detect-button");

function normalize(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[character];
  });
}

function setLoading(isLoading) {
  detectButton.disabled = isLoading;
  detectButton.textContent = isLoading ? "Searching..." : "Detect";
}

function levenshtein(a, b) {
  const rows = Array.from({ length: a.length + 1 }, (_, index) => [index]);
  for (let column = 1; column <= b.length; column += 1) rows[0][column] = column;

  for (let row = 1; row <= a.length; row += 1) {
    for (let column = 1; column <= b.length; column += 1) {
      const cost = a[row - 1] === b[column - 1] ? 0 : 1;
      rows[row][column] = Math.min(
        rows[row - 1][column] + 1,
        rows[row][column - 1] + 1,
        rows[row - 1][column - 1] + cost,
      );
    }
  }

  return rows[a.length][b.length];
}

function scoreMedicine(query, medicine) {
  const targets = [medicine.name, ...medicine.aliases].map(normalize);
  let bestScore = 0;

  targets.forEach((target) => {
    if (target === query) bestScore = Math.max(bestScore, 1);
    if (target.includes(query) || query.includes(target)) bestScore = Math.max(bestScore, 0.86);

    const distance = levenshtein(query, target);
    const similarity = 1 - distance / Math.max(query.length, target.length);
    bestScore = Math.max(bestScore, similarity);
  });

  return bestScore;
}

function findMedicine(rawQuery) {
  const query = normalize(rawQuery);
  if (!query) return null;

  const ranked = medicines
    .map((medicine) => ({ medicine, score: scoreMedicine(query, medicine) }))
    .sort((a, b) => b.score - a.score);

  const best = ranked[0];
  if (best.score >= 0.62) return best;
  return { medicine: null, score: 0, suggestions: ranked.slice(0, 3).map((item) => item.medicine.name) };
}

function renderMedicine(match) {
  const confidence = Math.round(match.score * 100);
  const diseaseList = match.medicine.diseaseArea.map((disease) => `<li>${disease}</li>`).join("");

  resultCard.innerHTML = `
    <div class="medicine-title">
      <h2>${match.medicine.name}</h2>
      <span class="match-badge">${confidence}% match</span>
    </div>
    <div class="detail-grid">
      <section class="detail-box">
        <h3>Generally Used For</h3>
        <p>${match.medicine.usedFor}</p>
      </section>
      <section class="detail-box">
        <h3>Common Disease Area</h3>
        <ul class="disease-list">${diseaseList}</ul>
      </section>
    </div>
    <section class="warning">
      <h3>Safety Note</h3>
      <p>${match.medicine.caution} This is not a diagnosis or prescription.</p>
    </section>
  `;
}

function getOpenFdaName(label) {
  const openfda = label.openfda || {};
  return (
    openfda.brand_name?.[0] ||
    openfda.generic_name?.[0] ||
    openfda.substance_name?.[0] ||
    "Medicine label result"
  );
}

function getOpenFdaSource(label) {
  const openfda = label.openfda || {};
  return [openfda.manufacturer_name?.[0], openfda.product_type?.[0]].filter(Boolean).join(" | ");
}

function splitIndications(text) {
  return text
    .replace(/\s+/g, " ")
    .split(/(?:\.\s+|;\s+|\n+)/)
    .map((item) => item.trim())
    .filter((item) => item.length > 20)
    .slice(0, 6);
}

function renderOnlineMedicine(label) {
  const name = escapeHtml(getOpenFdaName(label));
  const source = escapeHtml(getOpenFdaSource(label) || "FDA drug label");
  const indicationsText =
    label.indications_and_usage?.join(" ") ||
    label.purpose?.join(" ") ||
    label.description?.join(" ") ||
    "No indication text was available in this label result.";
  const warningText =
    label.warnings?.[0] ||
    label.warnings_and_cautions?.[0] ||
    label.boxed_warning?.[0] ||
    "Read the package label and ask a healthcare professional before using this medicine.";
  const diseaseItems = splitIndications(indicationsText);
  const diseaseList = diseaseItems.length
    ? diseaseItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : `<li>${escapeHtml(indicationsText)}</li>`;

  resultCard.innerHTML = `
    <div class="medicine-title">
      <h2>${name}</h2>
      <span class="match-badge">Internet result</span>
    </div>
    <div class="detail-grid">
      <section class="detail-box">
        <h3>Generally Used For</h3>
        <p>${escapeHtml(diseaseItems[0] || indicationsText)}</p>
      </section>
      <section class="detail-box">
        <h3>Diseases / Conditions</h3>
        <ul class="disease-list">${diseaseList}</ul>
      </section>
    </div>
    <section class="warning">
      <h3>Safety Note</h3>
      <p>${escapeHtml(warningText)} This is not a diagnosis or prescription.</p>
    </section>
    <p class="source-note">Source: ${source}</p>
  `;
}

function renderUnknown(match, query) {
  const safeQuery = escapeHtml(query);
  const suggestionButtons = match.suggestions
    .map((name) => `<button type="button" class="chip" data-medicine="${name}">${name}</button>`)
    .join("");

  resultCard.innerHTML = `
    <div class="medicine-title">
      <h2>No confident match</h2>
    </div>
    <section class="warning">
      <h3>Check the spelling</h3>
      <p>I could not confidently identify "${safeQuery}". Try the generic name, brand name, or a clearer spelling from the medicine strip.</p>
    </section>
    <div class="suggestions">
      <p>Closest examples:</p>
      ${suggestionButtons}
    </div>
  `;
}

function renderLoading(value) {
  resultCard.innerHTML = `
    <div class="empty-state">
      <span class="empty-icon" aria-hidden="true">+</span>
      <p>Searching online labels for "${escapeHtml(value)}"...</p>
    </div>
  `;
}

function buildOpenFdaQueries(query) {
  const safeQuery = query.replace(/"/g, "");
  return [
    `openfda.brand_name:"${safeQuery}"`,
    `openfda.generic_name:"${safeQuery}"`,
    `openfda.substance_name:"${safeQuery}"`,
    safeQuery,
  ];
}

async function searchOpenFdaMedicine(value) {
  const queries = buildOpenFdaQueries(value.trim());

  for (const query of queries) {
    const params = new URLSearchParams({
      search: query,
      limit: "1",
    });
    const response = await fetch(`https://api.fda.gov/drug/label.json?${params.toString()}`);

    if (response.status === 404) continue;
    if (!response.ok) throw new Error("Online medicine lookup failed.");

    const data = await response.json();
    if (data.results?.[0]) return data.results[0];
  }

  return null;
}

async function detectMedicine(value, options = {}) {
  const trimmedValue = value.trim();
  const match = findMedicine(trimmedValue);
  if (!match) {
    resultCard.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon" aria-hidden="true">+</span>
        <p>Type a medicine name to see what it is generally used for.</p>
      </div>
    `;
    return;
  }

  if (!options.localOnly) {
    renderLoading(trimmedValue);
    setLoading(true);

    try {
      const onlineMatch = await searchOpenFdaMedicine(trimmedValue);
      if (onlineMatch) {
        renderOnlineMedicine(onlineMatch);
        return;
      }
    } catch (error) {
      console.warn(error);
    } finally {
      setLoading(false);
    }
  }

  if (match.medicine) renderMedicine(match);
  else renderUnknown(match, trimmedValue);
}

medicines.slice(0, 10).forEach((medicine) => {
  const button = document.createElement("button");
  button.className = "chip";
  button.type = "button";
  button.textContent = medicine.name;
  button.dataset.medicine = medicine.name;
  exampleList.append(button);
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-medicine]");
  if (!button) return;
  input.value = button.dataset.medicine;
  detectMedicine(input.value);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  detectMedicine(input.value);
});

input.addEventListener("input", () => {
  if (input.value.trim().length >= 3) detectMedicine(input.value, { localOnly: true });
});
