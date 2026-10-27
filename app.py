import io, os, queue, re, subprocess, sys, threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import core

BG, PANEL, CARD, HOVER = "#0e1014", "#151821", "#1c2029", "#262b37"
ACC, ACC_H, MUTED = "#7c5cff", "#6a49f0", "#8b93a7"
KINDS = {"Моды": "mod", "Сборки": "modpack", "Ресурспаки": "resourcepack", "Шейдеры": "shader"}
LOADERS = ["Vanilla", "Fabric", "Quilt", "Forge", "NeoForge"]

ctk.set_appearance_mode("dark")


def open_folder(p):
    p = str(p)
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Cubix")
        self.geometry("1120x720")
        self.minsize(980, 620)
        self.configure(fg_color=BG)
        self.cfg = core.load_config()
        self.q = queue.Queue()
        self.busy = self.indet = False
        self.cur = None
        self.icons = []
        self.releases = []
        self.nav = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_sidebar()
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=0, column=1, sticky="nsew")
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)
        self.pages = {"play": self.build_play(box), "browse": self.build_browse(box),
                      "settings": self.build_settings(box)}
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")
        self.build_status()
        self.show("play")
        self.refresh()
        self.after(100, self.poll)
        threading.Thread(target=self.load_versions, daemon=True).start()

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

    # ───────── layout ─────────
    def build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, width=190)
        sb.grid(row=0, column=0, rowspan=2, sticky="nsw")
        sb.grid_propagate(False)
        ctk.CTkLabel(sb, text="▣ CUBIX", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=ACC).pack(pady=(28, 28), padx=20, anchor="w")
        for key, label in (("play", "Играть"), ("browse", "Моды и сборки"), ("settings", "Настройки")):
            b = ctk.CTkButton(sb, text=label, anchor="w", height=42, corner_radius=10,
                              fg_color="transparent", hover_color=HOVER,
                              font=ctk.CTkFont(size=15), command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=14, pady=3)
            self.nav[key] = b

    def build_status(self):
        f = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=44)
        f.grid(row=1, column=1, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(f, text="Готов", text_color=MUTED, anchor="w")
        self.status.grid(row=0, column=0, padx=20, pady=10, sticky="w")
        self.bar = ctk.CTkProgressBar(f, width=300, progress_color=ACC)
        self.bar.set(0)
        self.bar.grid(row=0, column=1, padx=20)

    def show(self, name):
        self.pages[name].tkraise()
        for k, b in self.nav.items():
            b.configure(fg_color=HOVER if k == name else "transparent")

    # ───────── play page ─────────
    def build_play(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(1, weight=1)
        f.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(f, fg_color=PANEL, corner_radius=16, width=330)
        left.grid(row=0, column=0, sticky="nsw", padx=(20, 10), pady=20)
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        ctk.CTkLabel(head, text="Сборки", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="＋", width=34, height=34, fg_color=ACC, hover_color=ACC_H,
                      command=self.new_dialog).pack(side="right")
        self.list = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list.grid(row=1, column=0, sticky="nsew", padx=6)
        ctk.CTkButton(left, text="Импорт .mrpack / .zip", fg_color=CARD, hover_color=HOVER,
                      height=38, command=self.import_file).grid(row=2, column=0, padx=16, pady=16, sticky="ew")

        right = ctk.CTkFrame(f, fg_color=PANEL, corner_radius=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 20), pady=20)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(30, 0))
        self.t_name = ctk.CTkLabel(top, text="Создай или импортируй сборку", anchor="w",
                                   font=ctk.CTkFont(size=30, weight="bold"))
        self.t_name.pack(fill="x")
        self.t_info = ctk.CTkLabel(top, text="", anchor="w", text_color=MUTED)
        self.t_info.pack(fill="x", pady=(4, 0))
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", pady=16)
        for text, fn in (("Моды…", self.go_mods), ("Папка", self.open_inst),
                         ("Удалить", self.delete_inst)):
            ctk.CTkButton(row, text=text, width=100, fg_color=CARD, hover_color=HOVER,
                          command=fn).pack(side="left", padx=(0, 8))

        bottom = ctk.CTkFrame(right, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=30, pady=30)
        bottom.grid_columnconfigure(1, weight=1)
        self.nick = ctk.CTkEntry(bottom, width=200, height=52, placeholder_text="Ник",
                                 font=ctk.CTkFont(size=16), fg_color=CARD, border_width=0)
        self.nick.insert(0, self.cfg["nick"])
        self.nick.grid(row=0, column=0)
        ctk.CTkButton(bottom, text="ИГРАТЬ", height=52, font=ctk.CTkFont(size=20, weight="bold"),
                      fg_color=ACC, hover_color=ACC_H, command=self.play).grid(
            row=0, column=1, sticky="ew", padx=(12, 0))
        return f

    def refresh(self):
        for w in self.list.winfo_children():
            w.destroy()
        insts = core.list_instances()
        for i in insts:
            sel = self.cur and self.cur["id"] == i["id"]
            ctk.CTkButton(self.list, anchor="w", height=62, corner_radius=12,
                          fg_color=ACC if sel else CARD, hover_color=ACC_H if sel else HOVER,
                          text=f"{i['name']}\n{i['mc']} • {i['loader'].capitalize()}",
                          font=ctk.CTkFont(size=14), command=lambda x=i["id"]: self.select(x)
                          ).pack(fill="x", pady=4, padx=4)
        ids = [i["id"] for i in insts] or ["—"]
        self.target.configure(values=ids)
        if self.target.get() not in ids:
            self.target.set(ids[0])

    def select(self, iid):
        self.cur = core.get_instance(iid)
        if self.cur:
            self.t_name.configure(text=self.cur["name"])
            self.t_info.configure(text=f"Minecraft {self.cur['mc']} • {self.cur['loader'].capitalize()}")
            self.target.set(iid)
        self.refresh()

    def new_dialog(self):
        w = ctk.CTkToplevel(self)
        w.title("Новая сборка")
        w.geometry("380x360")
        w.configure(fg_color=PANEL)
        w.transient(self)
        w.after(150, w.grab_set)
        name = ctk.CTkEntry(w, placeholder_text="Название", height=38)
        name.pack(fill="x", padx=24, pady=(24, 10))
        ctk.CTkLabel(w, text="Версия Minecraft", text_color=MUTED).pack(anchor="w", padx=24)
        ver = ctk.CTkComboBox(w, values=self.releases or ["1.21.1", "1.20.1", "1.19.4", "1.16.5"], height=38)
        ver.pack(fill="x", padx=24, pady=(0, 10))
        ctk.CTkLabel(w, text="Загрузчик модов", text_color=MUTED).pack(anchor="w", padx=24)
        ld = ctk.CTkOptionMenu(w, values=LOADERS, height=38, fg_color=CARD, button_color=HOVER)
        ld.pack(fill="x", padx=24, pady=(0, 10))

        def go():
            n = name.get().strip() or "Новая сборка"
            mc, l = ver.get().strip(), ld.get().lower()
            w.destroy()
            self.bg(lambda cb: core.create_instance(n, mc, l, cb),
                    lambda i: (self.select(i["id"]), self.status.configure(text="Сборка создана")))

        ctk.CTkButton(w, text="Создать", height=42, fg_color=ACC, hover_color=ACC_H,
                      command=go).pack(fill="x", padx=24, pady=20)

    def import_file(self):
        p = filedialog.askopenfilename(title="Сборка", filetypes=[("Сборки", "*.mrpack *.zip")])
        if p:
            self.bg(lambda cb: core.import_modpack(p, cb, self.cfg["cf_key"]), self.after_pack)

    def after_pack(self, res):
        inst, missing = res
        self.select(inst["id"])
        self.status.configure(text=f"Сборка «{inst['name']}» установлена")
        if missing:
            messagebox.showwarning("Не всё скачалось",
                                   "Не удалось скачать (положи вручную в mods):\n" + "\n".join(missing[:25]))

    def open_inst(self):
        if self.cur:
            open_folder(core.game_dir(self.cur))

    def delete_inst(self):
        if self.cur and messagebox.askyesno("Удалить", f"Удалить «{self.cur['name']}» вместе с миром и модами?"):
            core.delete_instance(self.cur)
            self.cur = None
            self.t_name.configure(text="Создай или импортируй сборку")
            self.t_info.configure(text="")
            self.refresh()

    def go_mods(self):
        self.show("browse")

    def play(self):
        if not self.cur:
            messagebox.showinfo("Cubix", "Сначала создай сборку (кнопка ＋)")
            return
        nick = self.nick.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", nick):
            messagebox.showwarning("Ник", "Ник: 3–16 символов, латиница, цифры и _")
            return
        self.cfg["nick"] = nick
        core.save_config(self.cfg)
        inst = self.cur
        self.bg(lambda cb: core.launch(inst, nick, self.cfg, cb),
                lambda p: self.status.configure(text="Игра запущена. Лог: launch.log в папке сборки"))

    # ───────── browse page ─────────
    def build_browse(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(f, fg_color=PANEL, corner_radius=16)
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        bar.grid_columnconfigure(0, weight=1)
        self.src = ctk.CTkSegmentedButton(bar, values=["Modrinth", "CurseForge"],
                                          selected_color=ACC, selected_hover_color=ACC_H)
        self.src.set("Modrinth")
        self.src.grid(row=0, column=1, padx=10, pady=14)
        self.kind = ctk.CTkSegmentedButton(bar, values=list(KINDS), selected_color=ACC,
                                           selected_hover_color=ACC_H)
        self.kind.set("Моды")
        self.kind.grid(row=0, column=2, padx=10)
        self.target = ctk.CTkOptionMenu(bar, values=["—"], width=170, fg_color=CARD, button_color=HOVER)
        self.target.grid(row=0, column=3, padx=10)
        self.q_entry = ctk.CTkEntry(bar, placeholder_text="Поиск: sodium, create, rlcraft…", height=40,
                                    fg_color=CARD, border_width=0)
        self.q_entry.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(14, 6), pady=(0, 14))
        self.q_entry.bind("<Return>", lambda e: self.do_search())
        ctk.CTkButton(bar, text="Найти", height=40, fg_color=ACC, hover_color=ACC_H,
                      command=self.do_search).grid(row=1, column=3, padx=10, pady=(0, 14), sticky="ew")
        self.results = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.results.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))
        self.results.grid_columnconfigure(0, weight=1)
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
            card = ctk.CTkFrame(self.results, fg_color=CARD, corner_radius=12)
            card.pack(fill="x", pady=4, padx=4)
            card.grid_columnconfigure(1, weight=1)
            ico = ctk.CTkLabel(card, text="", width=56, height=56)
            ico.grid(row=0, column=0, rowspan=2, padx=12, pady=10)
            ctk.CTkLabel(card, text=r["title"], anchor="w",
                         font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=1, sticky="ew", pady=(10, 0))
            ctk.CTkLabel(card, text=(r["desc"] or "")[:110] + f"   ⬇ {r['downloads']:,}", anchor="w",
                         text_color=MUTED).grid(row=1, column=1, sticky="ew", pady=(0, 10))
            ctk.CTkButton(card, width=130, height=36, fg_color=ACC, hover_color=ACC_H,
                          text="Установить" if kind == "modpack" else "В сборку",
                          command=lambda x=r: self.install(x, src, kind)).grid(row=0, column=2, rowspan=2, padx=14)
            if r.get("icon"):
                threading.Thread(target=self.load_icon, args=(r["icon"], ico), daemon=True).start()

    def load_icon(self, url, label):
        try:
            img = Image.open(io.BytesIO(core.fetch_bytes(url))).convert("RGBA").resize((56, 56))
            ci = ctk.CTkImage(img, size=(56, 56))

            def put():
                self.icons.append(ci)
                label.configure(image=ci)

            self.main(put)
        except Exception:
            pass

    def install(self, r, src, kind):
        key = self.cfg["cf_key"]
        if kind == "modpack":
            self.bg(lambda cb: core.modpack_from_source(src, r["id"], key, cb), self.after_pack)
            return
        inst = core.get_instance(self.target.get())
        if not inst:
            messagebox.showinfo("Cubix", "Сначала создай сборку")
            return
        self.bg(lambda cb: core.install_content(src, r["id"], kind, inst, key, cb),
                lambda got: self.status.configure(text="Установлено: " + ", ".join(got)))

    # ───────── settings ─────────
    def build_settings(self, parent):
        f = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=16)
        f.grid_columnconfigure(0, weight=1)

        def label(t):
            ctk.CTkLabel(f, text=t, text_color=MUTED, anchor="w").pack(fill="x", padx=30, pady=(18, 4))

        ctk.CTkLabel(f, text="Настройки", font=ctk.CTkFont(size=26, weight="bold"),
                     anchor="w").pack(fill="x", padx=30, pady=(28, 0))
        label("CurseForge API-ключ (бесплатно: console.curseforge.com). Нужен для поиска и сборок CurseForge")
        self.e_key = ctk.CTkEntry(f, height=40, show="•", fg_color=CARD, border_width=0)
        self.e_key.insert(0, self.cfg["cf_key"])
        self.e_key.pack(fill="x", padx=30)
        label("Путь к Java (пусто = скачать нужную автоматически)")
        self.e_java = ctk.CTkEntry(f, height=40, fg_color=CARD, border_width=0)
        self.e_java.insert(0, self.cfg["java"])
        self.e_java.pack(fill="x", padx=30)
        self.l_ram = ctk.CTkLabel(f, text="", text_color=MUTED, anchor="w")
        self.l_ram.pack(fill="x", padx=30, pady=(18, 4))
        self.s_ram = ctk.CTkSlider(f, from_=1, to=16, number_of_steps=15, progress_color=ACC,
                                   command=lambda v: self.l_ram.configure(text=f"Память по умолчанию: {int(v)} ГБ"))
        self.s_ram.set(self.cfg["ram_mb"] / 1024)
        self.l_ram.configure(text=f"Память по умолчанию: {int(self.cfg['ram_mb'] / 1024)} ГБ")
        self.s_ram.pack(fill="x", padx=30)
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=30)
        ctk.CTkButton(row, text="Сохранить", fg_color=ACC, hover_color=ACC_H, height=40,
                      command=self.save_settings).pack(side="left")
        ctk.CTkButton(row, text="Папка лаунчера", fg_color=CARD, hover_color=HOVER, height=40,
                      command=lambda: open_folder(core.ROOT)).pack(side="left", padx=10)
        return f

    def save_settings(self):
        self.cfg.update(cf_key=self.e_key.get().strip(), java=self.e_java.get().strip(),
                        ram_mb=int(self.s_ram.get()) * 1024)
        core.save_config(self.cfg)
        self.status.configure(text="Настройки сохранены")


if __name__ == "__main__":
    App().mainloop()
