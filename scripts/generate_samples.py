from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'sample_images';OUT.mkdir(exist_ok=True)
try:
    f_title=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',38)
    f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',25)
    f_small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',21)
except Exception:
    f_title=f=f_small=ImageFont.load_default()
def base(title):
    im=Image.new('RGB',(900,1200),'#f4efe0');d=ImageDraw.Draw(im);d.rounded_rectangle((70,55,830,1145),radius=24,outline='#555',width=5,fill='#fffdf5');d.rounded_rectangle((120,100,780,230),radius=18,fill='#1e5f8f');d.text((150,135),title,font=f_title,fill='white');return im,d
def compliant():
    im,d=base('PureSip Face Wash');y=300
    for line in ['NET QUANTITY 150 ml','MRP Rs. 299','Mfd: 08/2026','Customer Care: 1800-123-4567','Manufactured by PureSip Industries Pvt Ltd.','123 Industrial Area, Bengaluru','Country of Origin: India']:
        d.text((140,y),line,font=f,fill='#111');y+=110
    im.save(OUT/'sample_compliant.png')
def missing():
    im,d=base('FreshGlow Shampoo');y=310
    for line in ['NET QUANTITY 200 ml','MRP Rs. 249','Mfd: 07/2026','FreshGlow Hair Care']:
        d.text((140,y),line,font=f,fill='#111');y+=130
    im.save(OUT/'sample_missing_fields.png')
def conflict():
    im,d=base('Heritage Milk');d.text((140,310),'NET QUANTITY 500 ml',font=f,fill='#111');d.text((140,420),'MRP Rs. 99',font=f,fill='#111');d.text((515,420),'MRP Rs. 109',font=f_small,fill='#a00');d.text((140,540),'Mfd: 08/2026',font=f,fill='#111');d.text((140,670),'Customer Care 1800-000-000',font=f,fill='#111');d.text((140,800),'Manufactured by Heritage Foods Ltd.',font=f_small,fill='#111');d.text((140,875),'123 Industrial Area, New Delhi',font=f_small,fill='#111');im.save(OUT/'sample_conflicting_mrp.png')
if __name__=='__main__':compliant();missing();conflict();print('Generated',OUT)
