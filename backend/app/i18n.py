"""Localized explanation templates for the deterministic explainer.

The explanation is *rendered*, never generated: every sentence is a template
with {placeholder} slots filled from RecommendationResponse fields. Numbers,
units (°C, mg m⁻³, km/h, m, km), zone ids and coordinates stay in the
international notation shown on the map; only the wording around them changes.
A missing language falls back to English — never to a fabricated sentence.
"""

from __future__ import annotations

# English is the reference set — every other language must define every key.
_EN = {
    "searching": "Searching {km} km from {place}.",
    "searching_nodist": "Searching from {place}.",
    "unable": "Unable to make a reliable recommendation with the currently available data:",
    "no_candidates": "No candidate zones were acceptable — all candidates failed hard safety checks.",
    "rec_zone": "Recommended zone {id} at {lat}°N, {lon}°E ({bearing}° from {place}, {dist} km offshore).",
    "why_prefix": "Why: ",
    "weights": "Scores use ORCA's prototype decision weights — they are not scientifically validated.",
    "b_productivity": "productivity {v}/1",
    "b_risk": "risk {v}/1 (lower is better)",
    "b_sst": "SST {v} °C",
    "b_chl": "chlorophyll {v} mg m⁻³",
    "b_front": "thermal/front activity {v} (normalized)",
    "b_wave": "waves {v} m",
    "b_wind": "wind {v} km/h",
    "b_boundary": "{v} km from the maritime boundary",
    "route_ok": (
        "The suggested route is {km} km, about {h} h at your vessel speed, and it does not cross any "
        "restricted area or the India–Sri Lanka maritime boundary."
    ),
    "route_blocked": "WARNING: no fully compliant route could be generated to this zone.",
    "valid": "Valid for {t} IST.",
    "demo": "Data is DEMO / CACHED — not live observations.",
    "p_info": "Note:",
    "p_caution": "Caution:",
    "p_warning": "WARNING:",
    "p_critical": "CRITICAL:",
}

_TA = {
    "searching": "{place} -இலிருந்து {km} கி.மீ. சுற்றி தேடப்படுகிறது.",
    "searching_nodist": "{place} -இலிருந்து தேடப்படுகிறது.",
    "unable": "தற்போதைய தரவில் நம்பகமான பரிந்துரையை உருவாக்க முடியவில்லை:",
    "no_candidates": "எந்த இடமும் கடின பாதுகாப்புச் சோதனைகளில் தேறவில்லை.",
    "rec_zone": "பரிந்துரைக்கப்பட்ட இடம் {id}: {lat}°N, {lon}°E ({place} -இலிருந்து {bearing}°, கடற்கரையிலிருந்து {dist} கி.மீ.).",
    "why_prefix": "காரணம்: ",
    "weights": "மதிப்பெண்கள் ORCA-வின் தற்காலிக நிரல் எடைகளைப் பயன்படுத்துகின்றன — அவை அறிவியல்பூர்வமாக உறுதிப்படுத்தப்படவில்லை.",
    "b_productivity": "மீன் வாய்ப்பு {v}/1",
    "b_risk": "ஆபத்து {v}/1 (குறைவு நன்று)",
    "b_sst": "நீர் வெப்பநிலை {v} °C",
    "b_chl": "குளோரோபில் {v} mg m⁻³",
    "b_front": "நீர்வெப்ப முனைவு {v} (சாதாரணப்படுத்தப்பட்டது)",
    "b_wave": "அலைகள் {v} மீ",
    "b_wind": "காற்று {v} கி.மீ/மணி",
    "b_boundary": "கடல் எல்லையிலிருந்து {v} கி.மீ.",
    "route_ok": (
        "பரிந்துரைக்கப்பட்ட பாதை {km} கி.மீ., உங்கள் படகு வேகத்தில் சுமார் {h} மணி; "
        "இது எந்தத் தடைசெய்யப்பட்ட பகுதியையும் இந்தியா–இலங்கை கடல் எல்லையையும் தாண்டுவதில்லை."
    ),
    "route_blocked": "எச்சரிக்கை: இந்த இடத்திற்கு முழுமையாக இணங்கும் பாதை உருவாக்க முடியவில்லை.",
    "valid": "{t} IST வரை செல்லுபடியாகும்.",
    "demo": "தரவு DEMO / CACHED — நேரடி அளவீடுகள் அல்ல.",
    "p_info": "குறிப்பு:",
    "p_caution": "கவனம்:",
    "p_warning": "எச்சரிக்கை:",
    "p_critical": "ஆபத்து:",
}

_TE = {
    "searching": "{place} నుండి {km} కి.మీ. చుట్టూ వెతుకుతోంది.",
    "searching_nodist": "{place} నుండి వెతుకుతోంది.",
    "unable": "ప్రస్తుత డేటాతో నమ్మకమైన సిఫారసు చేయలేకపోయాము:",
    "no_candidates": "గట్టి భద్రతా పరీక్షలలో ఏ ప్రాంతమూ నిలవలేదు.",
    "rec_zone": "సిఫారసు చేసిన ప్రాంతం {id}: {lat}°N, {lon}°E ({place} నుండి {bearing}°, తీరం నుండి {dist} కి.మీ.).",
    "why_prefix": "కారణం: ",
    "weights": "స్కోర్లు ORCA యొక్క తాత్కాలిక నిర్ణయ బరువులను ఉపయోగిస్తాయి — అవి శాస్త్రీయంగా ధృవీకరించబడలేదు.",
    "b_productivity": "చేపల అవకాశం {v}/1",
    "b_risk": "ప్రమాదం {v}/1 (తక్కువ మంచిది)",
    "b_sst": "నీటి ఉష్ణోగ్రత {v} °C",
    "b_chl": "క్లోరోఫిల్ {v} mg m⁻³",
    "b_front": "ఉష్ణ సరిహద్దు కార్యాచరణ {v} (ప్రమాణీకృతం)",
    "b_wave": "అలలు {v} మీ",
    "b_wind": "గాలి {v} కి.మీ/గం",
    "b_boundary": "సముద్ర సరిహద్దుకు {v} కి.మీ.",
    "route_ok": (
        "సూచించిన మార్గం {km} కి.మీ., మీ పడవ వేగంతో సుమారు {h} గంటలు; ఇది ఏ నిషేధిత ప్రాంతాన్ని లేదా " +
        "భారత–శ్రీలంక సముద్ర సరిహద్దును దాటదు."
    ),
    "route_blocked": "హెచ్చరిక: ఈ ప్రాంతానికి పూర్తిగా అనుగుణమైన మార్గం రూపొందించలేకపోయాము.",
    "valid": "{t} IST వరకు చెల్లుతుంది.",
    "demo": "డేటా DEMO / CACHED — ప్రత్యక్ష కొలతలు కావు.",
    "p_info": "సూచన:",
    "p_caution": "జాగ్రత్త:",
    "p_warning": "హెచ్చరిక:",
    "p_critical": "ప్రమాదం:",
}

_ML = {
    "searching": "{place}-ൽ നിന്ന് {km} കി.മീ ചുറ്റി തിരയുന്നു.",
    "searching_nodist": "{place}-ൽ നിന്ന് തിരയുന്നു.",
    "unable": "നിലവിലെ ഡാറ്റയിൽ വിശ്വസനീയമായ ശുപാർശ തയ്യാറാക്കാനായില്ല:",
    "no_candidates": "കർക്കശമായ സുരക്ഷാ പരിശോധനകളിൽ ഒരു സ്ഥലവും വിജയിച്ചില്ല.",
    "rec_zone": "ശുപാർശ ചെയ്ത സ്ഥലം {id}: {lat}°N, {lon}°E ({place}-ൽ നിന്ന് {bearing}°, തീരത്തുനിന്ന് {dist} കി.മീ).",
    "why_prefix": "കാരണം: ",
    "weights": "സ്കോറുകൾ ORCA-യുടെ താൽക്കാലിക തീരുമാന ഭാരങ്ങൾ ഉപയോഗിക്കുന്നു — അവ ശാസ്ത്രീയമായി സ്ഥിരീകരിച്ചിട്ടില്ല.",
    "b_productivity": "മത്സ്യ സാധ്യത {v}/1",
    "b_risk": "അപകടസാധ്യത {v}/1 (കുറവാണ് നല്ലത്)",
    "b_sst": "ജല താപനില {v} °C",
    "b_chl": "ക്ലോറോഫിൽ {v} mg m⁻³",
    "b_front": "താപ മുന്നണി പ്രവർത്തനം {v} (സാമാന്യവൽകൃതം)",
    "b_wave": "തിരമാലകൾ {v} മീ",
    "b_wind": "കാറ്റ് {v} കി.മീ/മണിക്കൂർ",
    "b_boundary": "കടൽ അതിർത്തിയിൽ നിന്ന് {v} കി.മീ.",
    "route_ok": (
        "നിർദ്ദേശിച്ച പാത {km} കി.മീ., നിങ്ങളുടെ ബോട്ട് വേഗതയിൽ ഏകദേശം {h} മണിക്കൂർ; ഇത് ഒരു നിരോധിത " +
        "മേഖലയെയോ ഇന്ത്യ–ശ്രീലങ്ക കടൽ അതിർത്തിയെയോ മുറിക്കുന്നില്ല."
    ),
    "route_blocked": "മുന്നറിയിപ്പ്: ഈ സ്ഥലത്തേക്ക് പൂർണ്ണമായി അനുസരണയുള്ള പാത തയ്യാറാക്കാനായില്ല.",
    "valid": "{t} IST വരെ സാധുവാണ്.",
    "demo": "ഡാറ്റ DEMO / CACHED — തത്സമയ അളവുകൾ അല്ല.",
    "p_info": "കുറിപ്പ്:",
    "p_caution": "ശ്രദ്ധ:",
    "p_warning": "മുന്നറിയിപ്പ്:",
    "p_critical": "അപകടം:",
}

_HI = {
    "searching": "{place} से {km} किमी के आस-पास खोजा जा रहा है.",
    "searching_nodist": "{place} से खोज जारी है.",
    "unable": "उपलब्ध डेटा से भरोसेमंद सिफ़ारिश नहीं बन सकी:",
    "no_candidates": "कोई क्षेत्र कठोर सुरक्षा-जाँचें पार नहीं कर पाया.",
    "rec_zone": "सिफ़ारिश किया गया क्षेत्र {id}: {lat}°N, {lon}°E ({place} से {bearing}°, तट से {dist} किमी).",
    "why_prefix": "कारण: ",
    "weights": "स्कोर ORCA के अस्थायी निर्णय-भारों पर आधारित हैं — वैज्ञानिक रूप से सत्यापित नहीं हैं.",
    "b_productivity": "मछली की संभावना {v}/1",
    "b_risk": "जोखिम {v}/1 (कम = बेहतर)",
    "b_sst": "पानी का तापमान {v} °C",
    "b_chl": "क्लोरोफिल {v} mg m⁻³",
    "b_front": "तापमान-सीमा की सक्रियता {v} (सामान्यीकृत)",
    "b_wave": "लहरें {v} मी",
    "b_wind": "हवा {v} किमी/घंटा",
    "b_boundary": "समुद्री सीमा से {v} किमी",
    "route_ok": (
        "सुझाया रास्ता {km} किमी है, आपकी नाव की रफ़्तार से लगभग {h} घंटे; यह किसी प्रतिबंधित क्षेत्र या " +
        "भारत–श्रीलंका समुद्री सीमा को पार नहीं करता."
    ),
    "route_blocked": "चेतावनी: इस क्षेत्र के लिए पूरी तरह अनुरूप कोई रास्ता नहीं बनाया जा सका.",
    "valid": "{t} IST तक वैध.",
    "demo": "डेटा DEMO / CACHED — लाइव माप नहीं.",
    "p_info": "सूचना:",
    "p_caution": "सावधानी:",
    "p_warning": "चेतावनी:",
    "p_critical": "ख़तरा:",
}

_BN = {
    "searching": "{place} থেকে {km} কিমি এলাকা অনুসন্ধান করা হচ্ছে.",
    "searching_nodist": "{place} থেকে অনুসন্ধান চলছে.",
    "unable": "বর্তমান তথ্যে নির্ভরযোগ্য সুপারিশ তৈরি করা গেল না:",
    "no_candidates": "কড়া নিরাপত্তা-পরীক্ষায় কোনো জায়গাই উত্তীর্ণ হয়নি.",
    "rec_zone": "সুপারিশকৃত জায়গা {id}: {lat}°N, {lon}°E ({place} থেকে {bearing}°, উপকূল থেকে {dist} কিমি).",
    "why_prefix": "কারণ: ",
    "weights": "স্কোর ORCA-র সাময়িক সিদ্ধান্ত-ওজন ব্যবহার করে — বৈজ্ঞানিকভাবে যাচাই করা নয়.",
    "b_productivity": "মাছের সম্ভাবনা {v}/1",
    "b_risk": "ঝুঁকি {v}/1 (কম হলে ভালো)",
    "b_sst": "জলের তাপমাত্রা {v} °C",
    "b_chl": "ক্লোরোফিল {v} mg m⁻³",
    "b_front": "তাপ-সীমানা কার্যকলাপ {v} (স্বাভাবিকীকৃত)",
    "b_wave": "ঢেউ {v} মিটার",
    "b_wind": "বাতাস {v} কিমি/ঘণ্টা",
    "b_boundary": "সমুদ্রসীমা থেকে {v} কিমি",
    "route_ok": (
        "প্রস্তাবিত পথ {km} কিমি, আপনার নৌকার গতিতে প্রায় {h} ঘণ্টা; এটি কোনো নিষিদ্ধ এলাকা বা " +
        "ভারত–শ্রীলঙ্কা সমুদ্রসীমা অতিক্রম করে না."
    ),
    "route_blocked": "সতর্কবার্তা: এই জায়গায় পুরোপুরি মানানসই পথ তৈরি করা গেল না.",
    "valid": "{t} IST পর্যন্ত বৈধ.",
    "demo": "ডেটা DEMO / CACHED — সরাসরি পরিমাপ নয়.",
    "p_info": "তথ্য:",
    "p_caution": "সতর্কতা:",
    "p_warning": "সতর্কবার্তা:",
    "p_critical": "বিপদ:",
}

_OR = {
    "searching": "{place} ଠାରୁ {km} କି.ମି. ପରିସରରେ ଖୋଜାଯାଉଛି.",
    "searching_nodist": "{place} ଠାରୁ ଖୋଜା ଯାଉଛି.",
    "unable": "ବର୍ତ୍ତମାନର ତଥ୍ୟରୁ ବିଶ୍ୱସ୍ତ ପରାମର୍ଶ ତିଆରି ହେଲା ନାହିଁ:",
    "no_candidates": "କଠୋର ସୁରକ୍ଷା ପରୀକ୍ଷାରେ କୌଣସି ସ୍ଥାନ ପାସ୍ ହେଲା ନାହିଁ.",
    "rec_zone": "ପରାମର୍ଶିତ ସ୍ଥାନ {id}: {lat}°N, {lon}°E ({place} ଠାରୁ {bearing}°, ତଟରୁ {dist} କି.ମି).",
    "why_prefix": "କାରଣ: ",
    "weights": "ସ୍କୋର ORCA ର ସାମୟିକ ନିଷ୍ପତ୍ତି-ଓଜନ ବ୍ୟବହାର କରେ — ସେଗୁଡ଼ିକ ବୈଜ୍ଞାନିକ ଭାବରେ ଯାଞ୍ଚିତ ନୁହେଁ.",
    "b_productivity": "ମାଛ ସମ୍ଭାବନା {v}/1",
    "b_risk": "ବିପଦ {v}/1 (କମ୍ ଭଲ)",
    "b_sst": "ପାଣି ତାପମାତ୍ରା {v} °C",
    "b_chl": "କ୍ଲୋରୋଫିଲ୍ {v} mg m⁻³",
    "b_front": "ତାପ ସୀମା କାର୍ଯ୍ୟକଳାପ {v} (ସାଧାରଣୀକୃତ)",
    "b_wave": "ଢେଉ {v} ମିଟର",
    "b_wind": "ପବନ {v} କି.ମି/ଘଣ୍ଟା",
    "b_boundary": "ସମୁଦ୍ର ସୀମାରୁ {v} କି.ମି.",
    "route_ok": (
        "ପ୍ରସ୍ତାବିତ ପଥ {km} କି.ମି., ଆପଣଙ୍କ ନୌକା ବେଗରେ ପ୍ରାୟ {h} ଘଣ୍ଟା; ଏହା କୌଣସି ନିଷିଦ୍ଧ ଅଞ୍ଚଳ ବା " +
        "ଭାରତ–ଶ୍ରୀଲଙ୍କା ସମୁଦ୍ର ସୀମା ଅତିକ୍ରମ କରେ ନାହିଁ."
    ),
    "route_blocked": "ଚେତାବନୀ: ଏହି ସ୍ଥାନକୁ ସମ୍ପୂର୍ଣ୍ଣ ମାନ୍ୟତା ପଥ ତିଆରି ହେଲା ନାହିଁ.",
    "valid": "{t} IST ପର୍ଯ୍ୟନ୍ତ ବୈଧ.",
    "demo": "ତଥ୍ୟ DEMO / CACHED — ତତ୍କ୍ଷଣାତ୍ ମାପ ନୁହେଁ.",
    "p_info": "ଟିପ୍ପଣୀ:",
    "p_caution": "ସାବଧାନ:",
    "p_warning": "ଚେତାବନୀ:",
    "p_critical": "ବିପଦ:",
}

_GU = {
    "searching": "{place} થી {km} કિમી પરિસરમાં શોધાય છે.",
    "searching_nodist": "{place} થી શોધ ચાલુ છે.",
    "unable": "હાલના ડેટામાંથી વિશ્વસનીય ભલામણ બનાવી શકાઈ નથી:",
    "no_candidates": "કઠોર સલામતી તપાસમાં કોઈ વિસ્તાર પાસ થયો નથી.",
    "rec_zone": "ભલામણ કરેલ વિસ્તાર {id}: {lat}°N, {lon}°E ({place} થી {bearing}°, દરિયાકિનારાથી {dist} કિમી).",
    "why_prefix": "કારણ: ",
    "weights": "સ્કોર ORCA ના કામચલાઉ નિર્ણય-વજન વાપરે છે — તે વૈજ્ઞાનિક રીતે ચકાસાયેલા નથી.",
    "b_productivity": "માછલીની શક્યતા {v}/1",
    "b_risk": "જોખમ {v}/1 (ઓછું = સારું)",
    "b_sst": "પાણીનું તાપમાન {v} °C",
    "b_chl": "ક્લોરોફિલ {v} mg m⁻³",
    "b_front": "તાપમાન-સીમા પ્રવૃત્તિ {v} (સામાન્યીકૃત)",
    "b_wave": "મોજાં {v} મી",
    "b_wind": "પવન {v} કિમી/કલાક",
    "b_boundary": "દરિયાઈ સરહદથી {v} કિમી",
    "route_ok": (
        "સૂચવેલ માર્ગ {km} કિમી છે, તમારી હોડીની ઝડપે આશરે {h} કલાક; તે કોઈ પ્રતિબંધિત વિસ્તાર કે " +
        "ભારત–શ્રીલંકા દરિયાઈ સરહદને પાર કરતો નથી."
    ),
    "route_blocked": "ચેતવણી: આ વિસ્તાર માટે સંપૂર્ણ અનુરૂપ કોઈ માર્ગ બનાવી શકાયો નથી.",
    "valid": "{t} IST સુધી માન્ય.",
    "demo": "ડેટા DEMO / CACHED — લાઇવ માપન નથી.",
    "p_info": "નોંધ:",
    "p_caution": "સાવધાની:",
    "p_warning": "ચેતવણી:",
    "p_critical": "અતિ ગંભીર:",
}

_TEXTS: dict[str, dict[str, str]] = {"en": _EN, "ta": _TA, "te": _TE, "ml": _ML, "hi": _HI, "bn": _BN, "or": _OR, "gu": _GU}

# Spoken/written names for the LLM system prompt ("answer in Tamil" etc.).
LANGUAGE_NAMES = {
    "en": "English",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "hi": "Hindi",
    "bn": "Bengali",
    "or": "Odia",
    "gu": "Gujarati",
}


def texts(language: str) -> dict[str, str]:
    """Template table for a UI language (unknown → English)."""
    return _TEXTS.get((language or "en").split("-")[0], _EN)


def language_name(language: str) -> str:
    return LANGUAGE_NAMES.get((language or "en").split("-")[0], "English")
