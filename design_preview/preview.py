from unittest.mock import patch
from pathlib import Path
from PIL import ImageGrab
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main
config = main.default_config()
config['accounts'] = [dict(id=f'preview-{i}', name=name, username=f'player_{i}', password='unused', **({'wow_pid':'1234','wow_hwnd':'0x00012345'} if i==0 else {})) for i,name in enumerate(['Nightfall','Silvermoon','Stormkeeper','Ember'])]
with patch.object(main, 'load_config', return_value=config), patch.object(main, 'save_config'), patch.object(main.Launcher, 'first_run'), patch.object(main.Launcher, 'refresh_wob_status'), patch.object(main.Launcher, 'watch_last_wow_window'):
    app=main.Launcher()
    try:
        app.geometry('1100x760+20+20')
        app.attributes('-topmost', True)
        app.lift()
        for _ in range(10):
            app.update(); time.sleep(.05)
        def shot(name):
            for _ in range(4):
                app.update(); time.sleep(.05)
            box=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())
            ImageGrab.grab(bbox=box).save(Path(__file__).parent/name)
        shot('launcher.png')
        app.toggle_order_menu(config['accounts'][0]); app.update(); time.sleep(.25); app.update()
        shot('details.png')
        app.geometry('800x580+20+20'); app.update(); time.sleep(.2); app.update()
        shot('compact.png')
    finally:
        app.destroy()
print('Preview screenshots saved using sample accounts')
