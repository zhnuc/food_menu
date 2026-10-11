"""Resize the approved logo into platform launcher assets (no new illustration)."""
import json
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
logo=Image.open(ROOT/'web/assets/navigation/v1/256/logo.png').convert('RGBA')


def image(edge,foreground=False):
    canvas=Image.new('RGBA',(edge,edge),(241,247,236,0 if foreground else 255))
    limit=round(edge*(.53 if foreground else .75));scaled=logo.copy();scaled.thumbnail((limit,limit),Image.Resampling.LANCZOS)
    canvas.alpha_composite(scaled,((edge-scaled.width)//2,(edge-scaled.height)//2))
    return canvas


for density,edge in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
    directory=ROOT/'android/app/src/main/res'/('mipmap-'+density);directory.mkdir(parents=True,exist_ok=True)
    for name in ('ic_launcher.png','ic_launcher_round.png'):image(edge).save(directory/name)
    image(round(edge*2.25),True).save(directory/'ic_launcher_foreground.png')
directory=ROOT/'ios/App/App/Assets.xcassets/AppIcon.appiconset';directory.mkdir(parents=True,exist_ok=True)
image(1024).convert('RGB').save(directory/'AppIcon-512@2x.png')
(directory/'Contents.json').write_text(json.dumps({'images':[{'filename':'AppIcon-512@2x.png','idiom':'universal','platform':'ios','size':'1024x1024'}],'info':{'author':'xcode','version':1}},indent=2),encoding='utf-8')
print('Platform icons generated from approved logo')
