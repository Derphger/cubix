import io, os, queue, re, subprocess, sys, threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import core

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# палитра в духе Modrinth App
BG, RAIL, CARD, HOVER = "#16181c", "#1d1f23", "#26292f", "#34363c"
ACC, ACC_H, ACC_TXT, SEL = "#1bd96a", "#17b85a", "#06180d", "#173d2a"
MUTED = "#96a2b0"
PALETTE = ["#1bd96a", "#7c8cff", "#f0a020", "#ff6b6b", "#22c3e6", "#c98bff"]
KINDS = {"Моды": "mod", "Сборки": "modpack", "Ресурспаки": "resourcepack", "Шейдеры": "shader"}
LOADERS = ["Vanilla", "Fabric", "Quilt", "Forge", "NeoForge"]

ctk.set_appearance_mode("dark")


def fmt(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1000:
        return f"{n / 1e3:.0f}K"
    return str(n)


def open_folder(p):
    p = str(p)
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def color_for(name):
    return PALETTE[sum(map(ord, name)) % len(PALETTE)]


def green_btn(parent, text, command, **kw):
    o = dict(fg_color=ACC, hover_color=ACC_H, text_color=ACC_TXT, font=ctk.CTkFont(weight="bold"))
    o.update(kw)
    return ctk.CTkButton(parent, text=text, command=command, **o)


def grey_btn(parent, text, command, **kw):
    o = dict(fg_color=CARD, hover_color=HOVER)
    o.update(kw)
    return ctk.CTkButton(parent, text=text, command=command, **o)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Cubix")
        self.geometry("1200x760")
        self.minsize(1020, 640)
        self.configure(fg_color=BG)
        self.cfg = core.load_config()
        self.q = queue.Queue()
        self.busy = self.indet = self.browse_loaded = False
        self.cur = None
        self.icons = []
        self.releases = []
        self.nav = {}
        self.after(300, self.set_icon)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.build_rail()
        self.build_topbar()
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=1, column=1, sticky="nsew")
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)
        self.pages = {"library": self.build_library(box), "instance": self.build_instance(box),
                      "browse": self.build_browse(box), "skin": self.build_skin(box), "settings": self.build_settings(box)}
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self.build_status()
        self.show("library")
        self.refresh()
        self.after(100, self.poll)
        threading.Thread(target=self.load_versions, daemon=True).start()

    def set_icon(self):
        try:
            if sys.platform == "win32":
                self.iconbitmap(os.path.join(BASE, "icon.ico"))
        except Exception:
            pass

    # ───────── infrastructure ─────────
    def main(self, fn):
        self.q.put(("call", fn))

    def cb(self, text, frac=None):
        self.q.put(("p", text, frac))

    def bg(self, fn, done=None):
        if self.busy:
            self.status.configure(text="Подожди, идёт другая операция...")
            return
        self.busy = True

        def work():
            try:
                self.q.put(("done", done, fn(self.cb), None))
            except Exception as e:
                self.q.put(("done", done, None, e))

        threading.Thread(target=work, daemon=True).start()

    def set_bar(self, frac):
        if frac is None:
            if not self.indet:
                self.bar.configure(mode="indeterminate")
                self.bar.start()
                self.indet = True
        else:
            if self.indet:
                self.bar.stop()
                self.bar.configure(mode="determinate")
                self.indet = False
            self.bar.set(frac)

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "call":
                    m[1]()
                elif m[0] == "p":
                    self.status.configure(text=m[1])
                    self.set_bar(m[2])
                else:
                    _, fn, res, err = m
                    self.busy = False
                    self.set_bar(0)
                    if err:
                        self.status.configure(text=f"Ошибка: {err}")
                        messagebox.showerror("Ошибка", str(err))
                    elif fn:
                        fn(res)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def load_versions(self):
        try:
            r = core.release_ids()
            self.main(lambda: setattr(self, "releases", r))
        except Exception:
            pass

    # ───────── frame: rail / topbar / status ─────────
    def build_rail(self):
        rail = ctk.CTkFrame(self, fg_color=RAIL, corner_radius=0, width=92)
        rail.grid(row=0, column=0, rowspan=3, sticky="nsw")
        rail.pack_propagate(False)
        try:
            img = Image.open(os.path.join(BASE, "icon.png")).convert("RGBA")
            logo = ctk.CTkImage(img, size=(46, 46))
            ctk.CTkLabel(rail, image=logo, text="").pack(pady=(18, 20))
        except Exception:
            ctk.CTkLabel(rail, text="▣", font=ctk.CTkFont(size=34), text_color=ACC).pack(pady=(18, 20))

        def add(key, glyph, label, side="top"):
            b = ctk.CTkButton(rail, text=f"{glyph}\n{label}", width=72, height=64, corner_radius=14,
                              fg_color="transparent", hover_color=HOVER, text_color=MUTED,
                              font=ctk.CTkFont(size=12), command=lambda: self.show(key))
            b.pack(side=side, pady=4 if side == "top" else (4, 16))
            self.nav[key] = b

        add("library", "▦", "Библиотека")
        add("browse", "✦", "Каталог")
        add("skin", "☻", "Скин")
        add("settings", "⚙", "Настройки", side="bottom")

    def build_topbar(self):
        top = ctk.CTkFrame(self, fg_color="transparent", height=70)
        top.grid(row=0, column=1, sticky="ew", padx=28, pady=(14, 6))
        top.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(top, text="", anchor="w", font=ctk.CTkFont(size=24, weight="bold"))
        self.title_lbl.grid(row=0, column=0, sticky="w")
        chip = ctk.CTkFrame(top, fg_color=CARD, corner_radius=22)
        chip.grid(row=0, column=1, sticky="e")
        self.avatar = ctk.CTkLabel(chip, text=(self.cfg["nick"] or "?")[0].upper(), width=34, height=34,
                                   corner_radius=17, fg_color=ACC, text_color=ACC_TXT,
                                   font=ctk.CTkFont(weight="bold"))
        self.avatar.pack(side="left", padx=(6, 4), pady=6)
        self.nick = ctk.CTkEntry(chip, width=140, height=32, border_width=0, fg_color="transparent",
                                 placeholder_text="Ник", font=ctk.CTkFont(size=14))
        self.nick.insert(0, self.cfg["nick"])
        self.nick.pack(side="left", padx=(0, 12))
        self.nick.bind("<KeyRelease>", lambda e: self.avatar.configure(text=(self.nick.get() or "?")[0].upper()))

    def build_status(self):
        f = ctk.CTkFrame(self, fg_color=RAIL, corner_radius=0, height=38)
        f.grid(row=2, column=1, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(f, text="Готов", text_color=MUTED, anchor="w")
        self.status.grid(row=0, column=0, padx=24, pady=8, sticky="w")
        self.bar = ctk.CTkProgressBar(f, width=280, height=8, progress_color=ACC, fg_color=HOVER)
        self.bar.set(0)
        self.bar.grid(row=0, column=1, padx=24)

    def show(self, name):
        self.pages[name].tkraise()
        title = {"library": "Библиотека", "browse": "Каталог", "skin": "Скин", "settings": "Настройки",
                 "instance": "Библиотека  ›  " + (self.cur["name"] if self.cur else "")}[name]
        self.title_lbl.configure(text=title)
        for k, b in self.nav.items():
            sel = k == name or (name == "instance" and k == "library")
            b.configure(fg_color=SEL if sel else "transparent", text_color=ACC if sel else MUTED)
        if name == "browse" and not self.browse_loaded:
            self.browse_loaded = True
            self.do_search()

    # ───────── library ─────────
    def build_library(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(f, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=28, pady=(0, 8))
        green_btn(bar, "＋  Создать", self.new_dialog, height=38, width=120).pack(side="left")
        grey_btn(bar, "Импорт сборки", self.import_file, height=38).pack(side="left", padx=10)
        self.grid_area = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.grid_area.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 10))
        for c in range(3):
            self.grid_area.grid_columnconfigure(c, weight=1, uniform="cols")
        return f

    def refresh(self):
        for w in self.grid_area.winfo_children():
            w.destroy()
        insts = core.list_instances()
        if not insts:
            ctk.CTkLabel(self.grid_area, text="Пока пусто.\nСоздай сборку или импортируй .mrpack / .zip",
                         text_color=MUTED, font=ctk.CTkFont(size=16), justify="center").grid(
                row=0, column=0, columnspan=3, pady=120)
        for idx, i in enumerate(insts):
            self.make_card(i, idx)
        ids = [i["id"] for i in insts] or ["—"]
        self.target.configure(values=ids)
        self.skin_target.configure(values=ids)
        if self.skin_target.get() not in ids:
            self.skin_target.set(ids[0])
        if self.target.get() not in ids:
            self.target.set(ids[0])

    def make_card(self, i, idx):
        card = ctk.CTkFrame(self.grid_area, fg_color=CARD, corner_radius=16)
        card.grid(row=idx // 3, column=idx % 3, padx=8, pady=8, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)
        ico = ctk.CTkLabel(card, text=i["name"][:1].upper(), width=64, height=64, corner_radius=14,
                           fg_color=color_for(i["name"]), text_color="#101214",
                           font=ctk.CTkFont(size=30, weight="bold"))
        ico.grid(row=0, column=0, rowspan=2, padx=16, pady=16)
        name = i["name"] if len(i["name"]) <= 20 else i["name"][:19] + "…"
        t = ctk.CTkLabel(card, text=name, anchor="w", font=ctk.CTkFont(size=16, weight="bold"))
        t.grid(row=0, column=1, sticky="sw", pady=(16, 0))
        s = ctk.CTkLabel(card, text=f"{i['loader'].capitalize()} {i['mc']}", anchor="w", text_color=MUTED)
        s.grid(row=1, column=1, sticky="nw", pady=(0, 16))
        play = ctk.CTkButton(card, text="▶", width=40, height=40, corner_radius=20, fg_color=ACC,
                             hover_color=ACC_H, text_color=ACC_TXT,
                             command=lambda x=i: self.play_inst(x))
        play.grid(row=0, column=2, rowspan=2, padx=14)
        for w in (card, ico, t, s):
            w.bind("<Button-1>", lambda e, x=i["id"]: self.open_inst(x))
            w.configure(cursor="hand2")

    def new_dialog(self):
        w = ctk.CTkToplevel(self)
        w.title("Новая сборка")
        w.geometry("400x400")
        w.configure(fg_color=RAIL)
        w.transient(self)
        w.after(150, w.grab_set)
        ctk.CTkLabel(w, text="Новая сборка", font=ctk.CTkFont(size=20, weight="bold")).pack(
            anchor="w", padx=26, pady=(24, 10))
        name = ctk.CTkEntry(w, placeholder_text="Название", height=40, fg_color=CARD, border_width=0)
        name.pack(fill="x", padx=26, pady=(0, 10))
        ctk.CTkLabel(w, text="Версия Minecraft", text_color=MUTED).pack(anchor="w", padx=26)
        ver = ctk.CTkComboBox(w, values=self.releases or ["1.21.1", "1.20.1", "1.19.4", "1.16.5"],
                              height=40, fg_color=CARD, border_width=0, button_color=HOVER)
        ver.pack(fill="x", padx=26, pady=(0, 10))
        ctk.CTkLabel(w, text="Загрузчик модов", text_color=MUTED).pack(anchor="w", padx=26)
        ld = ctk.CTkOptionMenu(w, values=LOADERS, height=40, fg_color=CARD, button_color=HOVER)
        ld.pack(fill="x", padx=26, pady=(0, 10))

        def go():
            n = name.get().strip() or "Новая сборка"
            mc, l = ver.get().strip(), ld.get().lower()
            w.destroy()
            self.bg(lambda cb: core.create_instance(n, mc, l, cb),
                    lambda i: (self.open_inst(i["id"]), self.status.configure(text="Сборка создана")))

        green_btn(w, "Создать", go, height=44).pack(fill="x", padx=26, pady=20)

    def import_file(self):
        p = filedialog.askopenfilename(title="Сборка", filetypes=[("Сборки", "*.mrpack *.zip")])
        if p:
            self.bg(lambda cb: core.import_modpack(p, cb, self.cfg["cf_key"]), self.after_pack)

    def after_pack(self, res, btn=None):
        inst, missing = res
        if btn:
            btn.configure(text="✓ Установлено", state="disabled", fg_color=HOVER, text_color=MUTED)
        self.open_inst(inst["id"])
        self.status.configure(text=f"Сборка «{inst['name']}» установлена")
        if missing:
            messagebox.showwarning("Не всё скачалось",
                                   "Не удалось скачать (положи вручную в mods):\n" + "\n".join(missing[:25]))

    # ───────── instance page ─────────
    def build_instance(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(f, fg_color=CARD, corner_radius=18)
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(0, 12))
        head.grid_columnconfigure(1, weight=1)
        self.i_icon = ctk.CTkLabel(head, text="", width=88, height=88, corner_radius=18,
                                   font=ctk.CTkFont(size=40, weight="bold"), text_color="#101214")
        self.i_icon.grid(row=0, column=0, rowspan=2, padx=20, pady=20)
        self.i_name = ctk.CTkLabel(head, text="", anchor="w", font=ctk.CTkFont(size=26, weight="bold"))
        self.i_name.grid(row=0, column=1, sticky="sw", pady=(22, 0))
        self.i_sub = ctk.CTkLabel(head, text="", anchor="w", text_color=MUTED)
        self.i_sub.grid(row=1, column=1, sticky="nw")
        btns = ctk.CTkFrame(head, fg_color="transparent")
        btns.grid(row=0, column=2, rowspan=2, padx=20)
        green_btn(btns, "▶   Играть", lambda: self.play_inst(self.cur), width=150, height=46,
                  font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        grey_btn(btns, "＋ Контент", self.add_content, width=100, height=46, fg_color=HOVER,
                 hover_color="#42454d").pack(side="left", padx=8)
        grey_btn(btns, "Папка", self.open_dir, width=80, height=46, fg_color=HOVER,
                 hover_color="#42454d").pack(side="left")
        ctk.CTkButton(btns, text="🗑", width=46, height=46, fg_color=HOVER, hover_color="#7a2b2b",
                      command=self.delete_inst).pack(side="left", padx=(8, 0))

        tabs = ctk.CTkTabview(f, fg_color=CARD, corner_radius=18, segmented_button_selected_color=ACC,
                              segmented_button_selected_hover_color=ACC_H,
                              segmented_button_unselected_color=CARD)
        tabs.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 14))
        t1, t2, t3 = tabs.add("Контент"), tabs.add("Логи"), tabs.add("Настройки")
        for t in (t1, t2):
            t.grid_columnconfigure(0, weight=1)
            t.grid_rowconfigure(1, weight=1)
        self.c_count = ctk.CTkLabel(t1, text="", text_color=MUTED, anchor="w")
        self.c_count.grid(row=0, column=0, sticky="w", pady=(4, 6))
        self.clist = ctk.CTkScrollableFrame(t1, fg_color="transparent")
        self.clist.grid(row=1, column=0, sticky="nsew")
        ctk.CTkLabel(t2, text="launch.log", text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        grey_btn(t2, "Обновить", self.load_log, width=90, height=28, fg_color=HOVER).grid(
            row=0, column=0, sticky="e")
        self.logbox = ctk.CTkTextbox(t2, fg_color=BG, font=ctk.CTkFont(family="Consolas", size=12))
        self.logbox.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.i_ramlbl = ctk.CTkLabel(t3, text="", text_color=MUTED, anchor="w")
        self.i_ramlbl.pack(fill="x", pady=(10, 4))
        self.i_ram = ctk.CTkSlider(t3, from_=1, to=16, number_of_steps=15, progress_color=ACC,
                                   button_color=ACC, button_hover_color=ACC_H,
                                   command=lambda v: self.i_ramlbl.configure(text=f"Память для этой сборки: {int(v)} ГБ"))
        self.i_ram.pack(fill="x")
        green_btn(t3, "Сохранить", self.save_inst, width=130, height=38).pack(anchor="w", pady=20)
        return f

    def open_inst(self, iid):
        inst = core.get_instance(iid)
        if not inst:
            return
        self.cur = inst
        self.i_icon.configure(text=inst["name"][:1].upper(), fg_color=color_for(inst["name"]))
        self.i_name.configure(text=inst["name"])
        self.i_sub.configure(text=f"{inst['loader'].capitalize()} {inst['mc']}")
        ram = (inst.get("ram_mb") or self.cfg["ram_mb"]) // 1024
        self.i_ram.set(ram)
        self.i_ramlbl.configure(text=f"Память для этой сборки: {ram} ГБ")
        self.target.set(iid)
        self.load_content()
        self.load_log()
        self.refresh()
        self.show("instance")

    def load_content(self):
        for w in self.clist.winfo_children():
            w.destroy()
        if not self.cur:
            return
        mods = core.game_dir(self.cur) / "mods"
        files = sorted([p for p in mods.glob("*") if p.name.endswith((".jar", ".jar.disabled"))],
                       key=lambda p: p.name.lower()) if mods.exists() else []
        self.c_count.configure(text=f"Модов: {len(files)}")
        if not files:
            ctk.CTkLabel(self.clist, text="Пока нет модов. Нажми «＋ Контент», чтобы найти их в каталоге.",
                         text_color=MUTED).pack(pady=40)
        for p in files:
            row = ctk.CTkFrame(self.clist, fg_color=BG, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            on = not p.name.endswith(".disabled")
            sw = ctk.CTkSwitch(row, text=p.name.replace(".jar.disabled", ".jar"), progress_color=ACC,
                               command=lambda x=p: self.after(10, lambda: self.toggle_mod(x)))
            if on:
                sw.select()
            sw.pack(side="left", padx=12, pady=8)
            ctk.CTkButton(row, text="✕", width=32, height=28, fg_color="transparent", hover_color="#7a2b2b",
                          command=lambda x=p: self.after(10, lambda: self.del_mod(x))).pack(side="right", padx=8)

    def toggle_mod(self, p):
        new = p.with_name(p.name[:-9]) if p.name.endswith(".disabled") else p.with_name(p.name + ".disabled")
        p.rename(new)
        self.load_content()

    def del_mod(self, p):
        p.unlink(missing_ok=True)
        self.load_content()

    def load_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        p = core.INSTANCES / self.cur["id"] / "launch.log" if self.cur else None
        text = p.read_text("utf-8", errors="replace")[-20000:] if p and p.exists() else \
            "Лог появится после первого запуска."
        self.logbox.insert("1.0", text)
        self.logbox.configure(state="disabled")

    def save_inst(self):
        if self.cur:
            self.cur["ram_mb"] = int(self.i_ram.get()) * 1024
            core.save_instance(self.cur)
            self.status.configure(text="Сохранено")

    def add_content(self):
        if self.cur:
            self.target.set(self.cur["id"])
            self.kind.set("Моды")
            self.show("browse")
            self.do_search()

    def open_dir(self):
        if self.cur:
            open_folder(core.game_dir(self.cur))

    def delete_inst(self):
        if self.cur and messagebox.askyesno("Удалить", f"Удалить «{self.cur['name']}» вместе с миром и модами?"):
            core.delete_instance(self.cur)
            self.cur = None
            self.refresh()
            self.show("library")

    def play_inst(self, inst):
        nick = self.nick.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", nick):
            messagebox.showwarning("Ник", "Ник: 3–16 символов, латиница, цифры и _ (поле справа сверху)")
            return
        self.cfg["nick"] = nick
        core.save_config(self.cfg)
        self.bg(lambda cb: core.launch(inst, nick, self.cfg, cb),
                lambda p: self.status.configure(text="Игра запущена. Лог смотри во вкладке «Логи»"))

    # ───────── browse ─────────
    def build_browse(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(1, weight=1)
        f.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(f, fg_color=CARD, corner_radius=18, width=240)
        side.grid(row=0, column=0, sticky="ns", padx=(28, 12), pady=(0, 14))
        side.grid_propagate(False)
        side.pack_propagate(False)

        def lbl(t):
            ctk.CTkLabel(side, text=t, text_color=MUTED, anchor="w").pack(fill="x", padx=18, pady=(18, 6))

        lbl("Источник")
        self.src = ctk.CTkSegmentedButton(side, values=["Modrinth", "CurseForge"], selected_color=ACC,
                                          selected_hover_color=ACC_H, unselected_color=HOVER,
                                          command=lambda v: self.do_search())
        self.src.set("Modrinth")
        self.src.pack(fill="x", padx=18)
        lbl("Устанавливать в сборку")
        self.target = ctk.CTkOptionMenu(side, values=["—"], fg_color=HOVER, button_color=HOVER,
                                        button_hover_color="#42454d")
        self.target.pack(fill="x", padx=18)
        ctk.CTkLabel(side, text="Версия игры и загрузчик берутся из выбранной сборки.\n"
                                "Сборки из каталога ставятся как новые.",
                     text_color=MUTED, wraplength=200, justify="left", anchor="w").pack(
            fill="x", padx=18, pady=20)

        main = ctk.CTkFrame(f, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 28), pady=(0, 14))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)
        self.kind = ctk.CTkSegmentedButton(main, values=list(KINDS), selected_color=ACC,
                                           selected_hover_color=ACC_H, unselected_color=CARD,
                                           command=lambda v: self.do_search())
        self.kind.set("Моды")
        self.kind.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.q_entry = ctk.CTkEntry(main, placeholder_text="Поиск: sodium, create, rlcraft…", height=42,
                                    fg_color=CARD, border_width=0, corner_radius=12)
        self.q_entry.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.q_entry.bind("<Return>", lambda e: self.do_search())
        green_btn(main, "Найти", self.do_search, height=42, width=100).grid(row=1, column=1, padx=(10, 0), pady=(0, 10))
        self.results = ctk.CTkScrollableFrame(main, fg_color="transparent")
        self.results.grid(row=2, column=0, columnspan=2, sticky="nsew")
        return f

    def do_search(self):
        query, src, kind = self.q_entry.get().strip(), self.src.get(), KINDS[self.kind.get()]
        inst = core.get_instance(self.target.get())
        key = self.cfg["cf_key"]
        self.status.configure(text="Ищу...")

        def work():
            try:
                if src == "Modrinth":
                    res = core.mr_search(query, kind, inst)
                else:
                    if not key:
                        raise RuntimeError("Для CurseForge нужен API-ключ: Настройки")
                    res = core.cf_search(key, query, kind, inst)
                self.main(lambda: self.show_results(res, src, kind))
            except Exception as e:
                msg = str(e)
                self.main(lambda: self.status.configure(text=f"Ошибка поиска: {msg}"))

        threading.Thread(target=work, daemon=True).start()

    def show_results(self, res, src, kind):
        for w in self.results.winfo_children():
            w.destroy()
        self.icons.clear()
        self.status.configure(text=f"Найдено: {len(res)}")
        for r in res:
            card = ctk.CTkFrame(self.results, fg_color=CARD, corner_radius=16)
            card.pack(fill="x", pady=5, padx=2)
            card.grid_columnconfigure(1, weight=1)
            ico = ctk.CTkLabel(card, text="", width=76, height=76, fg_color=HOVER, corner_radius=14)
            ico.grid(row=0, column=0, rowspan=3, padx=14, pady=14)
            ctk.CTkLabel(card, text=r["title"], anchor="w",
                         font=ctk.CTkFont(size=17, weight="bold")).grid(row=0, column=1, sticky="sw", pady=(14, 0))
            ctk.CTkLabel(card, text=(r["desc"] or "")[:130], anchor="w", justify="left", wraplength=520,
                         text_color=MUTED).grid(row=1, column=1, sticky="nw")
            ctk.CTkLabel(card, text=f"⬇  {fmt(r['downloads'])}", anchor="w", text_color=MUTED).grid(
                row=2, column=1, sticky="nw", pady=(0, 12))
            btn = green_btn(card, "Установить", None, width=120, height=38)
            btn.configure(command=lambda x=r, b=btn: self.install(x, src, kind, b))
            btn.grid(row=0, column=2, rowspan=3, padx=16)
            if r.get("icon"):
                threading.Thread(target=self.load_icon, args=(r["icon"], ico), daemon=True).start()

    def load_icon(self, url, label):
        try:
            img = Image.open(io.BytesIO(core.fetch_bytes(url))).convert("RGBA").resize((76, 76))
            ci = ctk.CTkImage(img, size=(76, 76))

            def put():
                self.icons.append(ci)
                label.configure(image=ci)

            self.main(put)
        except Exception:
            pass

    def install(self, r, src, kind, btn):
        key = self.cfg["cf_key"]
        if kind == "modpack":
            self.bg(lambda cb: core.modpack_from_source(src, r["id"], key, cb),
                    lambda res: self.after_pack(res, btn))
            return
        inst = core.get_instance(self.target.get())
        if not inst:
            messagebox.showinfo("Cubix", "Сначала создай сборку")
            return

        def done(got):
            btn.configure(text="✓ Установлено", state="disabled", fg_color=HOVER, text_color=MUTED)
            self.status.configure(text="Установлено: " + ", ".join(got))
            if self.cur and self.cur["id"] == inst["id"]:
                self.load_content()

        self.bg(lambda cb: core.install_content(src, r["id"], kind, inst, key, cb), done)

    # ───────── skin ─────────
    def build_skin(self, parent):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=18)
        f.grid_columnconfigure(1, weight=1)
        self.skin_img = ctk.CTkLabel(f, text="Скин не выбран", width=190, height=300, fg_color=BG,
                                     corner_radius=16, text_color=MUTED)
        self.skin_img.grid(row=0, column=0, rowspan=6, padx=30, pady=30, sticky="n")
        ctk.CTkLabel(f, text="Свой скин", anchor="w", font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=1, sticky="sw", pady=(30, 4))
        ctk.CTkLabel(f, justify="left", anchor="w", text_color=MUTED, wraplength=520,
                     text="PNG 64×64 (скачать можно на namemc.com или minecraftskins.com).\n"
                          "Скин привязывается к твоему нику и ставится через мод CustomSkinLoader: "
                          "лаунчер скачает его сам. Видишь скин ты (и те, у кого тоже стоит мод)."
                     ).grid(row=1, column=1, sticky="nw")
        green_btn(f, "Выбрать PNG…", self.pick_skin, width=160, height=40).grid(
            row=2, column=1, sticky="w", pady=(18, 6))
        ctk.CTkLabel(f, text="Применить к сборке", text_color=MUTED, anchor="w").grid(
            row=3, column=1, sticky="w", pady=(14, 4))
        self.skin_target = ctk.CTkOptionMenu(f, values=["—"], width=260, fg_color=HOVER,
                                             button_color=HOVER, button_hover_color="#42454d")
        self.skin_target.grid(row=4, column=1, sticky="w")
        green_btn(f, "Применить", self.apply_skin_ui, width=160, height=40).grid(
            row=5, column=1, sticky="nw", pady=(12, 0))
        if core.SKIN_PNG.exists():
            self.show_skin(core.SKIN_PNG)
        return f

    def show_skin(self, path):
        img = core.skin_preview(path, 9)
        ci = ctk.CTkImage(img, size=(img.width // 2, img.height // 2))
        self.skin_ci = ci
        self.skin_img.configure(image=ci, text="")

    def pick_skin(self):
        p = filedialog.askopenfilename(title="Скин", filetypes=[("PNG", "*.png")])
        if not p:
            return
        try:
            core.set_skin(p)
            self.show_skin(core.SKIN_PNG)
            self.status.configure(text="Скин выбран. Нажми «Применить» для сборки")
        except Exception as e:
            messagebox.showerror("Скин", str(e))

    def apply_skin_ui(self):
        inst = core.get_instance(self.skin_target.get())
        nick = self.nick.get().strip()
        if not inst:
            messagebox.showinfo("Cubix", "Сначала создай сборку")
            return
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", nick):
            messagebox.showwarning("Ник", "Сначала впиши ник (поле справа сверху)")
            return
        self.bg(lambda cb: core.apply_skin(inst, nick, cb),
                lambda _: (self.status.configure(text=f"Скин применён к «{inst['name']}» для ника {nick}"),
                           self.cur and self.cur["id"] == inst["id"] and self.load_content()))

    # ───────── settings ─────────
    def build_settings(self, parent):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=18)
        f.grid_columnconfigure(0, weight=1)

        def label(t):
            ctk.CTkLabel(f, text=t, text_color=MUTED, anchor="w").pack(fill="x", padx=30, pady=(20, 6))

        label("CurseForge API-ключ (бесплатно: console.curseforge.com). Нужен для поиска и сборок CurseForge")
        self.e_key = ctk.CTkEntry(f, height=42, show="•", fg_color=BG, border_width=0)
        self.e_key.insert(0, self.cfg["cf_key"])
        self.e_key.pack(fill="x", padx=30)
        label("Путь к Java (пусто = скачать нужную автоматически)")
        self.e_java = ctk.CTkEntry(f, height=42, fg_color=BG, border_width=0)
        self.e_java.insert(0, self.cfg["java"])
        self.e_java.pack(fill="x", padx=30)
        self.l_ram = ctk.CTkLabel(f, text="", text_color=MUTED, anchor="w")
        self.l_ram.pack(fill="x", padx=30, pady=(20, 6))
        self.s_ram = ctk.CTkSlider(f, from_=1, to=16, number_of_steps=15, progress_color=ACC,
                                   button_color=ACC, button_hover_color=ACC_H,
                                   command=lambda v: self.l_ram.configure(text=f"Память по умолчанию: {int(v)} ГБ"))
        self.s_ram.set(self.cfg["ram_mb"] / 1024)
        self.l_ram.configure(text=f"Память по умолчанию: {int(self.cfg['ram_mb'] / 1024)} ГБ")
        self.s_ram.pack(fill="x", padx=30)
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=30)
        green_btn(row, "Сохранить", self.save_settings, height=40, width=130).pack(side="left")
        grey_btn(row, "Папка лаунчера", lambda: open_folder(core.ROOT), height=40, fg_color=HOVER,
                 hover_color="#42454d").pack(side="left", padx=10)
        return f

    def save_settings(self):
        self.cfg.update(cf_key=self.e_key.get().strip(), java=self.e_java.get().strip(),
                        ram_mb=int(self.s_ram.get()) * 1024)
        core.save_config(self.cfg)
        self.status.configure(text="Настройки сохранены")


if __name__ == "__main__":
    App().mainloop()
