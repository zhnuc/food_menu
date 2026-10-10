"""Small, numbered contact sheets; original evidence assets stay separate."""
import base64
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps


def contact_sheet(directory, frames, offset=0, max_edge=640):
    images=[]
    for frame in frames:
        with Image.open(directory/Path(frame['asset']).name) as source:
            image=ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((max_edge,max_edge),Image.Resampling.LANCZOS)
            images.append(image)
    columns=min(2,len(images));rows=(len(images)+columns-1)//columns
    width=max(image.width for image in images);height=max(image.height for image in images)
    header=28;gap=8
    sheet=Image.new('RGB',(columns*(width+gap)+gap,rows*(height+header+gap)+gap),'white')
    draw=ImageDraw.Draw(sheet)
    for index,image in enumerate(images):
        x=gap+(index%columns)*(width+gap);y=gap+(index//columns)*(height+header+gap)
        draw.text((x+4,y+2),f'ID {offset+index}',fill='black',font_size=22)
        sheet.paste(image,(x+(width-image.width)//2,y+header))
    output=io.BytesIO();sheet.save(output,format='JPEG',quality=88,subsampling=0)
    return base64.b64encode(output.getvalue()).decode(),len(output.getvalue()),sheet.size
