"""Front-end tests: the aerodrome field, run against the real app script.

The pilot's input is parsed in the browser, not on the server — which is where
the ETD bug lived (a typed '08.00' silently became 00:00). So this runs the
actual <script> from web/index.html through a real JavaScript engine, against a
DOM stub just rich enough to load it. No re-implementation: a rename or a typo
in index.html fails here.

Engine: JavaScriptCore, which ships with macOS — no node, no npm, no download.
On a machine without it the test skips rather than fails.

Run: python3 test_web.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

JSC = ("/System/Library/Frameworks/JavaScriptCore.framework"
       "/Versions/A/Helpers/jsc")

# A browser stand-in: enough DOM to load the app and drive the input logic.
SHIM = r"""
var LOG = [];
function El(id){ this.id=id; this.value=''; this.innerHTML=''; this.textContent='';
  this.className=''; this.hidden=false; this.style={}; this.dataset={}; this._on={}; }
El.prototype.addEventListener=function(e,f){ (this._on[e]=this._on[e]||[]).push(f); };
El.prototype.fire=function(e,a){ (this._on[e]||[]).forEach(function(f){ f(a||{}); }); };
El.prototype.querySelector=function(){ return null; };
El.prototype.querySelectorAll=function(){ return []; };
El.prototype.closest=function(){ return null; };
El.prototype.insertAdjacentHTML=function(){}; El.prototype.scrollIntoView=function(){};
El.prototype.focus=function(){ LOG.push('focus:'+this.id); };
El.prototype.appendChild=function(){};
var _els={};
var document={ getElementById:function(id){ return _els[id]||(_els[id]=new El(id)); },
  querySelectorAll:function(){ return []; }, querySelector:function(){ return null; },
  addEventListener:function(){}, createElement:function(){ return new El('x'); } };
var _ls={};
var localStorage={ getItem:function(k){ return _ls.hasOwnProperty(k)?_ls[k]:null; },
  setItem:function(k,v){ _ls[k]=String(v); }, removeItem:function(k){ delete _ls[k]; } };
var navigator={}; var window={ addEventListener:function(){} };
var crypto={ getRandomValues:function(a){ for(var i=0;i<a.length;i++) a[i]=(i*37+11)%256; return a; } };
window.crypto = crypto;
var indexedDB={ open:function(){ return {}; } };
function fetch(){ var t={ then:function(){return t;}, catch:function(){return t;},
  finally:function(){return t;} }; return t; }
function setTimeout(){ return 0; }
function alert(m){ LOG.push('alert:'+m); }
function prompt(){ return 'TESTROUTE'; }
function confirm(){ return true; }
"""

TESTS = r"""
function ok(label, got, exp){
  var g=JSON.stringify(got), e=JSON.stringify(exp);
  if(g!==e){ print("[FAIL] "+label+"\n   got "+g+"\n   exp "+e); throw new Error(label); }
  print("[ok] "+label);
}
var ads=document.getElementById("ads"), read=document.getElementById("adread");
function reading(){ return read.innerHTML.replace(/&nbsp;/g," ").replace(/<[^>]+>/g,"").trim(); }
// Type, don't call adRead() directly: the reading is only useful if it actually
// fires on input. Calling it by hand would still pass with the listener removed.
function type(text){ ads.value=text; ads.fire("input"); }

// The convention: position carries the role.
ads.value="CPH BER LGAV EDDK";
ok("flight order -> DEP, ARR, ENR", adRoles(), {dep:"CPH",arr:"BER",enr:["LGAV","EDDK"]});
ads.value="cph, ber. lgav  eddk";
ok("commas, dots and lowercase all work", adRoles(), {dep:"CPH",arr:"BER",enr:["LGAV","EDDK"]});
ads.value="CPH BER CPH LGAV BER";
ok("a repeated code is briefed once", adRoles(), {dep:"CPH",arr:"BER",enr:["LGAV"]});
ads.value="  EKVG  ";
ok("a lone departure leaves ARR empty", adRoles(), {dep:"EKVG",arr:"",enr:[]});
ads.value="";
ok("empty field yields nothing", adRoles(), {dep:"",arr:"",enr:[]});

// The rule is only acceptable while it stays visible — and it has to update as
// the pilot types, so these go through the input event, not a direct call.
type("CPH BER LGAV EDDK");
ok("typing shows what was understood", reading(), "DEP CPH  ·  ARR BER  ·  ENR LGAV, EDDK");
type("CPH");
ok("missing arrival is called out", reading().indexOf("ARR missing")>=0, true);
type("");
ok("clearing restores the instructions",
   read.className==="hint" && reading().indexOf("departure")>=0, true);

// Saved routes keep working, including the tech stops in the Starair defaults.
applyRoute({label:"CGN-AOI", dep:"CGN", arr:"BGY AOI", enr:"HHN BRU LGG"});
ok("tech-stop route fills the field in order", ads.value, "CGN BGY AOI HHN BRU LGG");
ok("...and every airport is still briefed",
   adRoles().enr.indexOf("AOI")>=0 && adRoles().arr==="BGY", true);
applyRoute({label:"legacy", dep:"CGN", arr:"BER", alt:"HAM", enr:"CPH HAM"});
ok("a route's old ALT and ENROUTE merge without repeats", adRoles().enr, ["HAM","CPH"]);

// An incomplete form must not reach the server.
LOG.length=0; ads.value="CPH";
document.getElementById("go").fire("click");
ok("one aerodrome blocks the request and focuses the field",
   LOG.indexOf("focus:ads")>=0, true);

print("\nALL PASSED");
"""


def main() -> int:
    if not os.path.exists(JSC):
        print(f"[skip] no JavaScript engine at {JSC} — front-end tests need macOS")
        return 0

    html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "web", "index.html")).read()
    script = re.search(r"<script>(.*)</script>", html, re.S)
    if not script:
        print("[FAIL] no <script> block found in web/index.html")
        return 1

    # Elements the app reads at load must start with their real markup content,
    # or the app captures an empty string as its "original" hint text.
    seeds = {m.group(1): m.group(2) for m in
             re.finditer(r'<p[^>]*\sid="([^"]+)"[^>]*>(.*?)</p>', html, re.S)}
    seed_js = ("var SEED=%s; Object.keys(SEED).forEach(function(k){"
               "document.getElementById(k).innerHTML=SEED[k]; });" % json.dumps(seeds))

    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, src in (("shim.js", SHIM), ("seed.js", seed_js),
                          ("app.js", script.group(1)), ("tests.js", TESTS)):
            p = os.path.join(d, name)
            open(p, "w").write(src)
            paths.append(p)
        r = subprocess.run([JSC] + paths, capture_output=True, text=True)

    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print(r.stderr.strip())
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
