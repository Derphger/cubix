"""Cubix core: версии Minecraft, Java, загрузчики модов, сборки, Modrinth / CurseForge."""
import hashlib, json, os, platform, re, shutil, subprocess, tarfile, threading, uuid, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(os.environ.get("CUBIX_HOME") or Path.home() / ".cubix")
LIBS, ASSETS, VERSIONS = ROOT / "libraries", ROOT / "assets", ROOT / "versions"
INSTANCES, RUNTIMES, TMP = ROOT / "instances", ROOT / "runtimes", ROOT / "tmp"
for _d in (LIBS, ASSETS, VERSIONS, INSTANCES, RUNTIMES, TMP):
    _d.mkdir(parents=True, exist_ok=True)

OS = {"Windows": "windows", "Linux": "linux", "Darwin": "osx"}.get(platform.system(), "linux")
MACHINE = platform.machine().lower()
ARM = MACHINE in ("arm64", "aarch64")
SEP = ";" if OS == "windows" else ":"
NOWIN = 0x08000000 if OS == "windows" else 0

S = requests.Session()
S.headers["User-Agent"] = "Cubix/1.0 (personal launcher)"

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
MR = "https://api.modrinth.com/v2"
CF = "https://api.curseforge.com/v1"
noop = lambda *a: None


# ───────────────────────── config ─────────────────────────
CFG = ROOT / "config.json"
DEFAULT = {"nick": "Player", "cf_key": "", "java": "", "ram_mb": 4096}


def load_config():
    try:
        return {**DEFAULT, **json.loads(CFG.read_text("utf-8"))}
    except Exception:
        return dict(DEFAULT)


def save_config(c):
    CFG.write_text(json.dumps(c, indent=2), "utf-8")


# ───────────────────────── utils ─────────────────────────
def download(url, path, sha1=None):
    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for _ in range(3):
        try:
            r = S.get(url, timeout=60, stream=True)
            r.raise_for_status()
            tmp = Path(str(path) + ".part")
            h = hashlib.sha1()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
            if sha1 and h.hexdigest() != sha1:
                raise IOError("sha1 не совпал")
            tmp.replace(path)
            return path
        except Exception as e:
            last = e
    raise RuntimeError(f"Не скачалось: {url} ({last})")


def fetch_all(jobs, cb, label, tolerant=False):
    """jobs: [(url, dst, sha1)]. Возвращает список имён файлов, которые не скачались."""
    n, failed, lock, done = len(jobs), [], threading.Lock(), [0]
    if not n:
        return failed

    def one(j):
        url, dst, sha = j
        try:
            if url:
                download(url, dst, sha)
        except Exception:
            if not tolerant:
                raise
            failed.append(Path(dst).name)
        with lock:
            done[0] += 1
            d = done[0]
        if d % 10 == 0 or d == n:
            cb(f"{label} {d}/{n}", d / n)

    with ThreadPoolExecutor(16) as ex:
        list(ex.map(one, jobs))
    return failed


def fetch_bytes(url):
    r = S.get(url, timeout=20)
    r.raise_for_status()
    return r.content


def safe_join(base, rel):
    base = Path(base).resolve()
    p = (base / rel).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        raise ValueError(f"Небезопасный путь в архиве: {rel}")
    return p


def extract_overrides(z, prefix, gd):
    for n in z.namelist():
        if n.startswith(prefix) and not n.endswith("/"):
            dst = safe_join(gd, n[len(prefix):])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(n))


def offline_uuid(name):
    h = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode()).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


# ───────────────────────── versions ─────────────────────────
def get_manifest():
    return S.get(MANIFEST, timeout=30).json()


def release_ids():
    return [v["id"] for v in get_manifest()["versions"] if v["type"] == "release"]


def os_match(n):
    if n == OS:
        return True
    if n == f"{OS}-arm64":
        return ARM
    if n == f"{OS}-x86":
        return not (ARM or "64" in MACHINE)
    return False


def rules_ok(rules):
    if not rules:
        return True
    ok = False
    for r in rules:
        m = True
        o = r.get("os")
        if o:
            if "name" in o and not os_match(o["name"]):
                m = False
            if o.get("arch") == "x86" and (ARM or "64" in MACHINE):
                m = False
            if o.get("arch") == "arm64" and not ARM:
                m = False
        if "features" in r:
            m = False
        if m:
            ok = r["action"] == "allow"
    return ok


def lib_path(name):
    parts = name.split(":")
    g, a, v = parts[0], parts[1], parts[2]
    cls = parts[3] if len(parts) > 3 else None
    ext = "jar"
    if "@" in v:
        v, ext = v.split("@")
    fn = f"{a}-{v}" + (f"-{cls}" if cls else "") + "." + ext
    return f"{g.replace('.', '/')}/{a}/{v}/{fn}"


def merge(p, c):
    m = {**p, **c}
    m["libraries"] = c.get("libraries", []) + p.get("libraries", [])
    if "arguments" in p or "arguments" in c:
        m["arguments"] = {
            k: p.get("arguments", {}).get(k, []) + c.get("arguments", {}).get(k, [])
            for k in ("game", "jvm")
        }
    m["_vanilla"] = p["_vanilla"]
    return m


def load_version(vid):
    local = VERSIONS / vid / f"{vid}.json"
    if local.exists():
        vj = json.loads(local.read_text("utf-8"))
    else:
        e = next((v for v in get_manifest()["versions"] if v["id"] == vid), None)
        if not e:
            raise RuntimeError(f"Версия {vid} не найдена")
        vj = S.get(e["url"], timeout=30).json()
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(vj), "utf-8")
    if "inheritsFrom" in vj:
        return merge(load_version(vj["inheritsFrom"]), vj)
    vj["_vanilla"] = vid
    return vj


# ───────────────────────── Java ─────────────────────────
def find_java(d):
    exe = "java.exe" if OS == "windows" else "java"
    for root, _, files in os.walk(d):
        if exe in files and os.path.basename(root) == "bin":
            return os.path.join(root, exe)


def ensure_java(major, cb=noop):
    d = RUNTIMES / str(major)
    j = find_java(d)
    if j:
        return j
    cb(f"Скачиваю Java {major}...", None)
    arch = "aarch64" if ARM else "x64"
    o = {"windows": "windows", "linux": "linux", "osx": "mac"}[OS]
    url = f"https://api.adoptium.net/v3/binary/latest/{major}/ga/{o}/{arch}/jre/hotspot/normal/eclipse"
    arc = RUNTIMES / f"{major}.archive"
    download(url, arc)
    d.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(arc):
        zipfile.ZipFile(arc).extractall(d)
    else:
        with tarfile.open(arc) as t:
            try:
                t.extractall(d, filter="data")
            except TypeError:
                t.extractall(d)
    arc.unlink()
    j = find_java(d)
    if not j:
        raise RuntimeError("Не удалось распаковать Java")
    if OS != "windows":
        os.chmod(j, 0o755)
    return j


# ───────────────────────── install / prepare ─────────────────────────
def prepare(vid, cb=noop):
    vj = load_version(vid)
    base = vj["_vanilla"]
    cl = vj["downloads"]["client"]
    client = VERSIONS / base / f"{base}.jar"
    cb("Скачиваю клиент...", None)
    download(cl["url"], client, cl["sha1"])

    jobs, cp, nat, seen = [], [], [], set()
    nat_dir = VERSIONS / vid / "natives"
    nat_dir.mkdir(parents=True, exist_ok=True)
    for lib in vj["libraries"]:
        if not rules_ok(lib.get("rules")):
            continue
        name = lib["name"]
        key = ":".join(p for i, p in enumerate(name.split(":")) if i != 2)
        if key in seen:
            continue
        seen.add(key)
        d = lib.get("downloads")
        art = d.get("artifact") if d else None
        if not art and "natives" not in lib:
            p = lib_path(name)
            art = {"path": p, "url": lib.get("url", "https://libraries.minecraft.net/") + p, "sha1": None}
        if art:
            dst = LIBS / art["path"]
            jobs.append((art.get("url"), dst, art.get("sha1")))
            cp.append(str(dst))
        nk = lib.get("natives", {}).get(OS)
        if nk and d and "classifiers" in d:
            c = d["classifiers"].get(nk.replace("${arch}", "64"))
            if c:
                dst = LIBS / c["path"]
                jobs.append((c["url"], dst, c.get("sha1")))
                nat.append((dst, lib.get("extract", {}).get("exclude", [])))
    fetch_all(jobs, cb, "Библиотеки")
    for p, excl in nat:
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.endswith("/") or any(n.startswith(e) for e in excl):
                    continue
                if not (nat_dir / n).exists():
                    z.extract(n, nat_dir)

    ai = vj["assetIndex"]
    idx = ASSETS / "indexes" / (ai["id"] + ".json")
    download(ai["url"], idx)
    objs = json.loads(idx.read_text("utf-8"))["objects"].values()
    ajobs = [
        (f"https://resources.download.minecraft.net/{o['hash'][:2]}/{o['hash']}",
         ASSETS / "objects" / o["hash"][:2] / o["hash"], o["hash"])
        for o in objs
    ]
    fetch_all(ajobs, cb, "Ассеты")
    return {"vj": vj, "cp": cp + [str(client)], "natives": str(nat_dir)}


META = {"fabric": "https://meta.fabricmc.net/v2", "quilt": "https://meta.quiltmc.org/v3"}


def install_fabriclike(mc, loader, lv=None):
    base = META[loader]
    if not lv:
        lst = S.get(f"{base}/versions/loader/{mc}", timeout=30).json()
        if not lst:
            raise RuntimeError(f"{loader} не поддерживает Minecraft {mc}")
        lv = next((x["loader"]["version"] for x in lst if x["loader"].get("stable", True)),
                  lst[0]["loader"]["version"])
    pj = S.get(f"{base}/versions/loader/{mc}/{lv}/profile/json", timeout=30).json()
    vid = pj["id"]
    (VERSIONS / vid).mkdir(parents=True, exist_ok=True)
    (VERSIONS / vid / f"{vid}.json").write_text(json.dumps(pj), "utf-8")
    return vid


def install_forge(mc, kind, ver, cb=noop):
    if not ver:
        if kind == "forge":
            promos = S.get("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json",
                           timeout=30).json()["promos"]
            ver = promos.get(f"{mc}-recommended") or promos.get(f"{mc}-latest")
        else:
            parts = mc.split(".")
            prefix = f"{parts[1]}.{parts[2] if len(parts) > 2 else '0'}."
            vs = S.get("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge",
                       timeout=30).json()["versions"]
            c = [v for v in vs if v.startswith(prefix) and "beta" not in v]
            ver = c[-1] if c else None
        if not ver:
            raise RuntimeError(f"{kind} не найден для Minecraft {mc}")
    if kind == "forge":
        url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{ver}/forge-{mc}-{ver}-installer.jar"
    else:
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{ver}/neoforge-{ver}-installer.jar"

    cache_f = ROOT / "loaders.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    key = f"{kind}-{mc}-{ver}"
    if key in cache and (VERSIONS / cache[key]).exists():
        return cache[key]

    vj = prepare(mc, cb)["vj"]
    java = ensure_java(vj.get("javaVersion", {}).get("majorVersion", 8), cb)
    jar = ROOT / "installers" / f"{key}.jar"
    cb(f"Скачиваю установщик {kind}...", None)
    download(url, jar)
    prof = ROOT / "launcher_profiles.json"
    if not prof.exists():
        prof.write_text('{"profiles":{}}')
    cb(f"Устанавливаю {kind} (это долго)...", None)
    r = subprocess.run([java, "-jar", str(jar), "--installClient", str(ROOT)],
                       capture_output=True, text=True, cwd=ROOT, creationflags=NOWIN,
                       stdin=subprocess.DEVNULL)
    if r.returncode:
        raise RuntimeError("Установщик упал:\n" + (r.stdout + r.stderr)[-800:])
    cands = [d for d in os.listdir(VERSIONS) if ver in d and kind in d.lower()]
    if not cands:
        raise RuntimeError("Установщик отработал, но версия не появилась")
    cache[key] = cands[0]
    cache_f.write_text(json.dumps(cache))
    return cands[0]


def install_loader(mc, loader, lv=None, cb=noop):
    load_version(mc)
    if loader == "vanilla":
        return mc
    if loader in META:
        return install_fabriclike(mc, loader, lv)
    if loader in ("forge", "neoforge"):
        return install_forge(mc, loader, lv, cb)
    raise RuntimeError(f"Неизвестный загрузчик: {loader}")


# ───────────────────────── instances ─────────────────────────
def slug(n):
    return re.sub(r'[\\/:*?"<>|]', "_", n).strip(" .") or "instance"


def unique_id(name):
    base = slug(name)
    n, k = base, 2
    while (INSTANCES / n).exists():
        n, k = f"{base} ({k})", k + 1
    return n


def list_instances():
    out = []
    for d in sorted(INSTANCES.iterdir()):
        f = d / "instance.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text("utf-8")))
            except Exception:
                pass
    return out


def get_instance(iid):
    f = INSTANCES / iid / "instance.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else None


def save_instance(i):
    (INSTANCES / i["id"]).mkdir(parents=True, exist_ok=True)
    (INSTANCES / i["id"] / "instance.json").write_text(json.dumps(i, indent=2, ensure_ascii=False), "utf-8")


def delete_instance(i):
    shutil.rmtree(INSTANCES / i["id"], ignore_errors=True)


def game_dir(inst):
    p = INSTANCES / inst["id"] / "minecraft"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_instance(name, mc, loader, cb=noop, loader_version=None):
    vid = install_loader(mc, loader, loader_version, cb)
    inst = {"id": unique_id(name), "name": name, "mc": mc, "loader": loader, "version_id": vid}
    save_instance(inst)
    game_dir(inst)
    prepare(vid, cb)
    return inst


# ───────────────────────── launch ─────────────────────────
def expand(args, variables):
    out = []
    for a in args:
        if isinstance(a, dict):
            if not rules_ok(a.get("rules")):
                continue
            v = a["value"]
            items = v if isinstance(v, list) else [v]
        else:
            items = [a]
        for s in items:
            for k, val in variables.items():
                s = s.replace("${%s}" % k, val)
            out.append(s)
    return out


def launch(inst, nick, cfg, cb=noop):
    prep = prepare(inst["version_id"], cb)
    vj = prep["vj"]
    java = cfg.get("java") or ensure_java(vj.get("javaVersion", {}).get("majorVersion", 8), cb)
    gd = game_dir(inst)
    variables = {
        "auth_player_name": nick, "auth_uuid": offline_uuid(nick), "auth_access_token": "0",
        "auth_session": "0", "auth_xuid": "0", "clientid": "0", "user_type": "legacy",
        "user_properties": "{}", "version_name": inst["version_id"],
        "version_type": vj.get("type", "release"), "game_directory": str(gd),
        "assets_root": str(ASSETS), "game_assets": str(ASSETS),
        "assets_index_name": vj["assetIndex"]["id"], "natives_directory": prep["natives"],
        "launcher_name": "Cubix", "launcher_version": "1.0", "classpath": SEP.join(prep["cp"]),
        "library_directory": str(LIBS), "classpath_separator": SEP,
    }
    if "arguments" in vj:
        jvm = expand(vj["arguments"]["jvm"], variables)
        game = expand(vj["arguments"]["game"], variables)
    else:
        jvm = expand(["-Djava.library.path=${natives_directory}", "-cp", "${classpath}"], variables)
        game = expand(vj["minecraftArguments"].split(), variables)
    ram = inst.get("ram_mb") or cfg.get("ram_mb", 4096)
    cmd = [java, f"-Xmx{ram}M", *jvm, vj["mainClass"], *game]
    cb("Запускаю игру...", None)
    log = open(INSTANCES / inst["id"] / "launch.log", "w", encoding="utf-8")
    return subprocess.Popen(cmd, cwd=gd, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=NOWIN)


# ───────────────────────── Modrinth ─────────────────────────
def loaders_for(loader):
    return ["quilt", "fabric"] if loader == "quilt" else [loader]


def mr_search(query, kind, inst=None):
    facets = [[f"project_type:{kind}"]]
    if inst and kind != "modpack":
        facets.append([f"versions:{inst['mc']}"])
        if kind == "mod" and inst["loader"] != "vanilla":
            facets.append([f"categories:{l}" for l in loaders_for(inst["loader"])])
    r = S.get(f"{MR}/search", params={"query": query, "facets": json.dumps(facets), "limit": 30},
              timeout=30)
    r.raise_for_status()
    return [{"id": h["project_id"], "title": h["title"], "desc": h["description"],
             "downloads": h["downloads"], "icon": h.get("icon_url")} for h in r.json()["hits"]]


SUBDIR = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}


def mr_install(pid, kind, inst, cb, seen=None):
    seen = seen if seen is not None else set()
    if pid in seen:
        return []
    seen.add(pid)
    params = {"game_versions": json.dumps([inst["mc"]])}
    if kind == "mod" and inst["loader"] != "vanilla":
        params["loaders"] = json.dumps(loaders_for(inst["loader"]))
    r = S.get(f"{MR}/project/{pid}/version", params=params, timeout=30)
    r.raise_for_status()
    vs = r.json()
    if not vs:
        raise RuntimeError(f"Нет версии под Minecraft {inst['mc']} / {inst['loader']}")
    v = vs[0]
    f = next((x for x in v["files"] if x["primary"]), v["files"][0])
    cb(f"Скачиваю {f['filename']}...", None)
    download(f["url"], game_dir(inst) / SUBDIR[kind] / f["filename"], f["hashes"].get("sha1"))
    got = [f["filename"]]
    if kind == "mod":
        for d in v.get("dependencies", []):
            if d["dependency_type"] == "required" and d.get("project_id"):
                got += mr_install(d["project_id"], kind, inst, cb, seen)
    return got


def mr_modpack(pid, cb):
    r = S.get(f"{MR}/project/{pid}/version", timeout=30)
    r.raise_for_status()
    v = r.json()[0]
    f = next((x for x in v["files"] if x["primary"]), v["files"][0])
    cb("Скачиваю сборку...", None)
    p = download(f["url"], TMP / f["filename"], f["hashes"].get("sha1"))
    try:
        return import_modpack(p, cb)
    finally:
        p.unlink(missing_ok=True)


# ───────────────────────── CurseForge ─────────────────────────
CF_CLASS = {"mod": 6, "modpack": 4471, "resourcepack": 12, "shader": 6552}
CF_LOADER = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


def cf(key, method, path, **kw):
    r = S.request(method, CF + path, headers={"x-api-key": key, "Accept": "application/json"},
                  timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def cf_url(f):
    return f.get("downloadUrl") or \
        f"https://mediafilez.forgecdn.net/files/{f['id'] // 1000}/{f['id'] % 1000}/{quote(f['fileName'])}"


def cf_search(key, query, kind, inst=None):
    p = {"gameId": 432, "classId": CF_CLASS[kind], "searchFilter": query,
         "sortField": 2, "sortOrder": "desc", "pageSize": 30}
    if inst and kind != "modpack":
        p["gameVersion"] = inst["mc"]
        if kind == "mod" and inst["loader"] in CF_LOADER:
            p["modLoaderType"] = CF_LOADER[inst["loader"]]
    return [{"id": m["id"], "title": m["name"], "desc": m["summary"], "downloads": m["downloadCount"],
             "icon": (m.get("logo") or {}).get("thumbnailUrl")} for m in cf(key, "GET", "/mods/search", params=p)["data"]]


def cf_install(key, mid, kind, inst, cb, seen=None):
    seen = seen if seen is not None else set()
    if mid in seen:
        return []
    seen.add(mid)
    p = {"pageSize": 1, "gameVersion": inst["mc"]}
    if kind == "mod" and inst["loader"] in CF_LOADER:
        p["modLoaderType"] = CF_LOADER[inst["loader"]]
    files = cf(key, "GET", f"/mods/{mid}/files", params=p)["data"]
    if not files:
        raise RuntimeError(f"Нет файла под Minecraft {inst['mc']} / {inst['loader']}")
    f = files[0]
    cb(f"Скачиваю {f['fileName']}...", None)
    download(cf_url(f), game_dir(inst) / SUBDIR[kind] / Path(f["fileName"]).name)
    got = [f["fileName"]]
    if kind == "mod":
        for d in f.get("dependencies", []):
            if d["relationType"] == 3:
                try:
                    got += cf_install(key, d["modId"], kind, inst, cb, seen)
                except Exception:
                    pass
    return got


def cf_modpack(key, mid, cb):
    f = cf(key, "GET", f"/mods/{mid}/files", params={"pageSize": 1})["data"][0]
    cb("Скачиваю сборку...", None)
    p = download(cf_url(f), TMP / Path(f["fileName"]).name)
    try:
        return import_modpack(p, cb, key)
    finally:
        p.unlink(missing_ok=True)


def install_content(src, pid, kind, inst, key, cb):
    if src == "Modrinth":
        return mr_install(pid, kind, inst, cb)
    return cf_install(key, pid, kind, inst, cb)


def modpack_from_source(src, pid, key, cb):
    return mr_modpack(pid, cb) if src == "Modrinth" else cf_modpack(key, pid, cb)


# ───────────────────────── modpack import ─────────────────────────
def import_modpack(path, cb=noop, key=""):
    """Возвращает (instance, список_не_скачавшихся_файлов)."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    if "modrinth.index.json" in names:
        return _import_mrpack(z, cb)
    if "manifest.json" in names:
        return _import_cf(z, cb, key)
    raise RuntimeError("Неизвестный формат: нужен .mrpack (Modrinth) или .zip (CurseForge)")


def _import_mrpack(z, cb):
    idx = json.loads(z.read("modrinth.index.json"))
    deps = idx["dependencies"]
    mc, loader, lv = deps["minecraft"], "vanilla", None
    for k, n in (("fabric-loader", "fabric"), ("quilt-loader", "quilt"),
                 ("neoforge", "neoforge"), ("forge", "forge")):
        if k in deps:
            loader, lv = n, deps[k]
            break
    inst = create_instance(idx["name"], mc, loader, cb, lv)
    gd = game_dir(inst)
    jobs = []
    for f in idx["files"]:
        if f.get("env", {}).get("client") == "unsupported":
            continue
        jobs.append((f["downloads"][0], safe_join(gd, f["path"]), f["hashes"].get("sha1")))
    missing = fetch_all(jobs, cb, "Моды", tolerant=True)
    for pre in ("overrides/", "client-overrides/"):
        extract_overrides(z, pre, gd)
    return inst, missing


def _import_cf(z, cb, key):
    if not key:
        raise RuntimeError("Для сборок CurseForge нужен API-ключ (Настройки)")
    m = json.loads(z.read("manifest.json"))
    mc = m["minecraft"]["version"]
    loader, lv = "vanilla", None
    mls = m["minecraft"].get("modLoaders") or []
    if mls:
        ml = next((x for x in mls if x.get("primary")), mls[0])
        loader, lv = ml["id"].split("-", 1)
    inst = create_instance(m.get("name", "CurseForge сборка"), mc, loader, cb, lv)
    gd = game_dir(inst)
    fids = [f["fileID"] for f in m["files"]]
    pids = list({f["projectID"] for f in m["files"]})
    cb("Получаю список модов...", None)
    files, classes = [], {}
    for i in range(0, len(fids), 200):
        files += cf(key, "POST", "/mods/files", json={"fileIds": fids[i:i + 200]})["data"]
    for i in range(0, len(pids), 200):
        for mod in cf(key, "POST", "/mods", json={"modIds": pids[i:i + 200]})["data"]:
            classes[mod["id"]] = mod.get("classId")
    folder = {6: "mods", 12: "resourcepacks", 6552: "shaderpacks"}
    jobs = [(cf_url(f), gd / folder.get(classes.get(f["modId"]), "mods") / Path(f["fileName"]).name, None)
            for f in files]
    missing = fetch_all(jobs, cb, "Моды", tolerant=True)
    got = {f["id"] for f in files}
    missing += [f"fileID {i}" for i in fids if i not in got]
    extract_overrides(z, m.get("overrides", "overrides") + "/", gd)
    return inst, missing
