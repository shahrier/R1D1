"""Read-only local visual-memory dashboard for filming. No robot controls."""
import json
import re
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from memory_command import active_folder

ROOT = Path(__file__).resolve().parent / 'runtime'
HTML = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>R1D1 / Visual memory</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif}*{box-sizing:border-box}body{margin:0;background:#10191c;color:#e7f1ed;padding:28px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}h1{font-size:28px;margin:0;letter-spacing:-1px}h1 span{color:#7cdaba;font-weight:400}small{color:#a2b9b5}.tag{border:1px solid #38544c;padding:8px 12px;border-radius:30px;font-size:12px;color:#a6ecd3}.stats{display:flex;gap:12px;margin-bottom:18px}.stat{background:#1a2a2b;border:1px solid #29403c;border-radius:12px;padding:14px 20px;min-width:145px}.stat b{display:block;font-size:27px;color:#9ae6c9}.stat span{font-size:12px;color:#b1c3bc}main{display:grid;grid-template-columns:1.15fr 1fr;gap:18px}.panel{background:#172326;border:1px solid #2a4140;border-radius:16px;overflow:hidden}h2{font-size:14px;letter-spacing:.05em;margin:0;padding:17px 20px;color:#b6d4c8}img{display:block;width:100%;object-fit:contain;background:#111a1b}#camera{aspect-ratio:4/3}#map{aspect-ratio:1000/720}.caption{padding:15px 20px;color:#adbfba;font-size:13px;line-height:1.5}.footer{margin-top:18px;color:#9fb4ac;font-size:12px;line-height:1.6}.controls{display:flex;gap:12px;padding:12px 20px;align-items:center}input{flex:1;accent-color:#7cdaba}button{border:1px solid #45645a;background:#233c34;color:#dcf3e6;border-radius:8px;padding:8px 12px;cursor:pointer}#status{color:#a4dcca}a{color:#9ae6c9}@media(max-width:850px){main{grid-template-columns:1fr}.stats{flex-wrap:wrap}body{padding:16px}}
</style></head><body><header><div><h1>R1D1 <span>/ Visual memory</span></h1><small>Camera landmarks · wheel odometry · verified image revisits</small></div><div class="tag">READ-ONLY · NO MOTION CONTROLS</div></header><section class="stats"><div class="stat"><b id="views">—</b><span>recorded views</span></div><div class="stat"><b id="revisits">—</b><span>visual revisit candidates</span></div><div class="stat"><b id="calibration">—</b><span>calibration fit / pixels</span></div><div class="stat"><b id="inliers">—</b><span>strongest revisit / inliers</span></div></section><main><section class="panel"><h2 id="viewtitle">CAMERA LANDMARKS</h2><img id="camera"><div class="controls"><button onclick="mode=!mode;render()">Color / features</button><input id="slider" type="range" min="0" value="0" oninput="selected=+this.value;following=false;render()"><button onclick="following=true;poll()">Latest</button></div><div class="caption" id="viewcaption">Waiting for a recorded view…</div></section><section class="panel"><h2>CHECKPOINT GRAPH</h2><img id="map"><div class="caption" id="status">Waiting for a map…</div></section></main><div class="footer">Metric scale comes from wheel odometry. Image matches are verified with feature geometry; a match is not a certified position.<br>This experimental graph is not a depth map, obstacle map, or whole-house navigation system.</div><script>
let data=null,selected=0,following=true,mode=true;
function render(){if(!data||!data.nodes.length)return; selected=Math.min(selected,data.nodes.length-1);let n=data.nodes[selected];document.getElementById('camera').src=(mode?'/features/':'/frame/')+selected+'.jpg?v='+data.nodes.length;document.getElementById('viewtitle').textContent='VIEW '+(selected+1)+' / '+data.nodes.length+' · '+(mode?'TRACKED LANDMARKS':'RECORDED CAMERA');let p=n.pose_odometry;document.getElementById('viewcaption').textContent=n.features+' visual features · '+n.label+' · wheel position '+p[0].toFixed(2)+', '+p[1].toFixed(2)+' m · heading '+(p[2]*180/Math.PI).toFixed(0)+'°';document.getElementById('slider').value=selected;}
async function poll(){try{let r=await fetch('/data',{cache:'no-store'});if(!r.ok)throw Error('No active map');data=await r.json();document.getElementById('views').textContent=data.nodes.length;document.getElementById('revisits').textContent=data.revisits.length;document.getElementById('calibration').textContent=data.camera_calibration?data.camera_calibration.rms_pixels.toFixed(2):'—';document.getElementById('inliers').textContent=Math.max(0,...data.revisits.map(x=>x.inliers));document.getElementById('slider').max=Math.max(0,data.nodes.length-1);document.getElementById('map').src='/trajectory.png?v='+data.nodes.length;let result=data.result;document.getElementById('status').textContent=result&&result.start_recognized?'START VIEW RECOGNIZED · '+result.start_geometric_inliers+' geometric inliers':data.revisits.length?'Image revisit candidates found. Inspect their geometry before drawing conclusions.':'Building visual memory from recorded views.';if(following)selected=data.nodes.length-1;render();}catch(e){document.getElementById('status').textContent='Waiting for an active visual map.';}}
poll();setInterval(poll,2000);
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        target=urlparse(self.path).path
        try:
            if target=='/': return self.send_data(HTML.encode(),'text/html')
            folder=active_folder(ROOT)
            data=json.loads((folder/'map.json').read_text())
            if target=='/data':
                for node in data['nodes']:node.pop('photo',None)
                result=folder/'result.json'
                if result.exists():data['result']=json.loads(result.read_text())
                return self.send_data(json.dumps(data).encode(),'application/json')
            if target=='/trajectory.png':return self.send_data((folder/'trajectory.png').read_bytes(),'image/png')
            match=re.fullmatch(r'/(frame|features)/(\d+)\.jpg',target)
            if match:
                index=int(match.group(2))
                if not 0<=index<len(data['nodes']):return self.send_error(404)
                path=Path(data['nodes'][index]['photo']).resolve() if match.group(1)=='frame' else folder/f'features-{index}.jpg'
                if not path.is_relative_to(ROOT.resolve()):return self.send_error(403)
                return self.send_data(path.read_bytes(),'image/jpeg')
            self.send_error(404)
        except (OSError,ValueError,KeyError):self.send_error(503,'No active map yet')

    def send_data(self,data,mime):
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass

if __name__=='__main__':
    print('Read-only visual-memory dashboard on port 8090',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8090),Handler).serve_forever()
