import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ocr import run_ocr
from app.extract import extract_fields
from app.compliance import evaluate, load_rules
from app.config import RULES_PATH
root=Path(__file__).resolve().parents[1]
for name in ['sample_compliant.png','sample_missing_fields.png','sample_conflicting_mrp.png']:
    p=root/'sample_images'/name
    b,boxes,w=run_ocr(p,'mock')
    r=evaluate([{'quality':{'sharpness_score':90,'contrast_score':90,'glare_score':95},'boxes':boxes,'fields':extract_fields(boxes)}],load_rules(RULES_PATH))
    print(name,'=>',r['overall_status'],r['summary'])
