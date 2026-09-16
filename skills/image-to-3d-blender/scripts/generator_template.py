"""Generator template for one volumetric study. Copy, rename, fill in build().

Run:  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python craft_<slug>.py
Then: python3 <skill>/scripts/merge_manifest.py

Conventions: metres, Z up, ground (or waterline) at Z=0, the side the reference
shows facing -Y. Seed every random choice so the output is reproducible."""
import importlib.util, math, random
from pathlib import Path
spec=importlib.util.spec_from_file_location('studio',Path(__file__).resolve().parent/'studio.py')  # or the skill's absolute path
studio=importlib.util.module_from_spec(spec); spec.loader.exec_module(studio)
from mathutils import Vector

SLUG='my-object'; TITLE='My object'; CHINESE=''; SOURCE='/abs/path/reference.png'
DESCRIPTION='One sentence on what is modelled and what is interpreted.'
rng=random.Random(1)

def build(b):
 stone=studio.mat('Worn limestone',(.32,.31,.28),'stone',flat=True)
 timber=studio.mat('Weathered timber',(.2,.13,.08),'wood',flat=True)
 # Every magic number gets a why-comment: '0.16 m rise, the reference's seven treads reach the 1.1 m quay'.
 studio.box(b,stone,(0,0,.25),(2,1,.5))
 studio.tube(b,timber,[(0,0,.5),(0,0,2.2)],[.08,.05])

studio.clear_scene()          # the factory startup file has a cube; without this it exports too
b=studio.Builder(); build(b); b.emit()
studio.export(SLUG,TITLE,CHINESE,DESCRIPTION,source=SOURCE,light=1.0,view=(.95,-1.2,.83))
