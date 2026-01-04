import json
from kivy.app import App
from kivy.lang import Builder
from kivy.properties import ListProperty, StringProperty, BooleanProperty, NumericProperty
from kivy.clock import Clock
from kivy.utils import platform

from core.state import load_state, save_state, add_favorite, remove_favorite, MAX_FAVORITES
from core.tibia import fetch_character_snapshot
from core.utilities import BlessConfig, calc_blessings, rashid_today, next_server_save_utc, to_cet, calc_stamina_offline
import os
import traceback
from datetime import datetime

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView


KV = '''
#:import dp kivy.metrics.dp

<NavBtn@Button>:
    size_hint_x: None
    width: dp(140)

<RootUI@BoxLayout>:
    orientation: "vertical"
    padding: dp(10)
    spacing: dp(10)

    BoxLayout:
        size_hint_y: None
        height: dp(54)
        spacing: dp(8)

        Label:
            text: "[b]Tibia Tools[/b] — Android"
            markup: True
            font_size: "18sp"
            halign: "left"
            valign: "middle"
            text_size: self.size

        Label:
            text: app.status_text
            color: (0.2, 0.6, 0.2, 1) if "ON" in app.status_text else (0.6,0.2,0.2,1)
            size_hint_x: None
            width: dp(140)
            halign: "right"
            valign: "middle"
            text_size: self.size

    BoxLayout:
        size_hint_y: None
        height: dp(46)
        spacing: dp(8)

        NavBtn:
            text: "Favoritos"
            on_release: app.go("favorites")
        NavBtn:
            text: "Utilidades"
            on_release: app.go("utilities")

        Widget:

    ScreenManager:
        id: sm

        Screen:
            name: "favorites"
            BoxLayout:
                orientation: "vertical"
                spacing: dp(10)

                BoxLayout:
                    size_hint_y: None
                    height: dp(48)
                    spacing: dp(8)

                    TextInput:
                        id: name_in
                        hint_text: "Nome do personagem..."
                        multiline: False
                        on_text_validate: app.on_add_favorite(self.text)

                    Button:
                        text: "Adicionar"
                        size_hint_x: None
                        width: dp(110)
                        on_release: app.on_add_favorite(name_in.text)

                Label:
                    text: "Favoritos (máx. %d):" % app.max_favorites
                    size_hint_y: None
                    height: dp(24)

                RecycleView:
                    id: fav_list
                    viewclass: "FavRow"
                    data: [{"name": n} for n in app.favorites]
                    scroll_type: ["bars","content"]
                    bar_width: dp(6)

                    RecycleBoxLayout:
                        default_size: None, dp(46)
                        default_size_hint: 1, None
                        size_hint_y: None
                        height: self.minimum_height
                        orientation: "vertical"
                        spacing: dp(6)

                BoxLayout:
                    size_hint_y: None
                    height: dp(70)
                    spacing: dp(8)

                    ToggleButton:
                        id: mon
                        text: "Monitorar (foreground)"
                        state: "down" if app.monitoring else "normal"
                        on_state: app.on_toggle_monitor(self.state == "down")

                    Label:
                        text: "Intervalo (s):"
                        size_hint_x: None
                        width: dp(100)
                        halign: "right"
                        valign: "middle"
                        text_size: self.size

                    Spinner:
                        text: str(app.interval_seconds)
                        values: ["15","20","30","45","60","90","120"]
                        size_hint_x: None
                        width: dp(90)
                        on_text: app.on_interval_change(self.text)

                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(8)

                    Button:
                        text: "Testar Notificação"
                        on_release: app.notify("Tibia Tools", "Notificação de teste")

                    Button:
                        text: "Snapshot agora"
                        on_release: app.on_snapshot()

                Label:
                    text: app.last_snapshot_text
                    size_hint_y: None
                    height: dp(28)
                    color: (0.3,0.3,0.3,1)

        Screen:
            name: "utilities"

            TabbedPanel:
                do_default_tab: False

                TabbedPanelItem:
                    text: "Blessings"
                    BoxLayout:
                        orientation: "vertical"
                        spacing: dp(10)
                        padding: dp(8)

                        GridLayout:
                            cols: 2
                            spacing: dp(8)
                            size_hint_y: None
                            height: self.minimum_height

                            Label:
                                text: "Level:"
                                size_hint_y: None
                                height: dp(30)
                                halign: "left"
                                valign: "middle"
                                text_size: self.size

                            TextInput:
                                id: bl_level
                                text: "120"
                                input_filter: "int"
                                multiline: False

                            Label:
                                text: "Regulares (0-5):"
                                size_hint_y: None
                                height: dp(30)
                                halign: "left"
                                valign: "middle"
                                text_size: self.size

                            Spinner:
                                id: bl_reg
                                text: "5"
                                values: ["0","1","2","3","4","5"]

                            Label:
                                text: "Enhanced (0-2):"
                                size_hint_y: None
                                height: dp(30)
                                halign: "left"
                                valign: "middle"
                                text_size: self.size

                            Spinner:
                                id: bl_enh
                                text: "2"
                                values: ["0","1","2"]

                            Label:
                                text: "Tipo de mundo:"
                                size_hint_y: None
                                height: dp(30)
                                halign: "left"
                                valign: "middle"
                                text_size: self.size

                            Spinner:
                                id: bl_world
                                text: "Optional PvP"
                                values: ["Optional PvP","Open PvP","Retro Open PvP"]

                        BoxLayout:
                            size_hint_y: None
                            height: dp(46)
                            spacing: dp(8)

                            CheckBox:
                                id: bl_twist
                                active: True
                                on_active: app.on_bless_changed()
                            Label:
                                text: "Incluir Twist of Fate"
                                halign: "left"
                                valign: "middle"
                                text_size: self.size

                            CheckBox:
                                id: bl_inq
                                active: True
                                on_active: app.on_bless_changed()
                            Label:
                                text: "Desconto Inquisition (pacote 5)"
                                halign: "left"
                                valign: "middle"
                                text_size: self.size

                        BoxLayout:
                            size_hint_y: None
                            height: dp(40)
                            spacing: dp(8)
                            Button:
                                text: "Calcular"
                                on_release: app.on_bless_calc()
                            Button:
                                text: "Editar custos"
                                on_release: app.toggle_bless_cfg()

                        BoxLayout:
                            id: bless_cfg_box
                            orientation: "vertical"
                            spacing: dp(6)
                            size_hint_y: None
                            height: dp(0)
                            opacity: 0

                            GridLayout:
                                cols: 2
                                spacing: dp(6)
                                size_hint_y: None
                                height: self.minimum_height

                                Label:
                                    text: "Threshold (lvl):"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_thr
                                    input_filter: "int"
                                    text: str(app.bless_cfg_threshold)

                                Label:
                                    text: "Regular base:"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_reg_base
                                    input_filter: "int"
                                    text: str(app.bless_cfg_regular_base)

                                Label:
                                    text: "Regular step:"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_reg_step
                                    input_filter: "int"
                                    text: str(app.bless_cfg_regular_step)

                                Label:
                                    text: "Enhanced base:"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_enh_base
                                    input_filter: "int"
                                    text: str(app.bless_cfg_enhanced_base)

                                Label:
                                    text: "Enhanced step:"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_enh_step
                                    input_filter: "int"
                                    text: str(app.bless_cfg_enhanced_step)

                                Label:
                                    text: "Twist cost:"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_twist
                                    input_filter: "int"
                                    text: str(app.bless_cfg_twist)

                                Label:
                                    text: "Inq desconto (%):"
                                    halign: "left"; valign: "middle"
                                    text_size: self.size
                                TextInput:
                                    id: cfg_inq
                                    input_filter: "int"
                                    text: str(app.bless_cfg_inq_discount)

                            Button:
                                text: "Salvar custos"
                                size_hint_y: None
                                height: dp(42)
                                on_release: app.save_bless_cfg()

                        Label:
                            text: app.bless_out
                            markup: True

                TabbedPanelItem:
                    text: "Rashid & SS"
                    BoxLayout:
                        orientation: "vertical"
                        padding: dp(10)
                        spacing: dp(10)

                        Label:
                            text: app.rashid_out
                            markup: True

                        Label:
                            text: app.ss_out
                            markup: True

                        Button:
                            text: "Atualizar agora"
                            size_hint_y: None
                            height: dp(42)
                            on_release: app.update_rashid_and_ss()

                TabbedPanelItem:
                    text: "Stamina"
                    BoxLayout:
                        orientation: "vertical"
                        padding: dp(10)
                        spacing: dp(10)

                        GridLayout:
                            cols: 2
                            spacing: dp(8)
                            size_hint_y: None
                            height: self.minimum_height

                            Label:
                                text: "Stamina atual (HH:MM):"
                                halign: "left"; valign: "middle"
                                text_size: self.size
                            TextInput:
                                id: st_cur
                                text: "38:45"
                                multiline: False

                            Label:
                                text: "Meta (HH:MM):"
                                halign: "left"; valign: "middle"
                                text_size: self.size
                            TextInput:
                                id: st_tgt
                                text: "42:00"
                                multiline: False

                        BoxLayout:
                            size_hint_y: None
                            height: dp(40)
                            spacing: dp(8)
                            CheckBox:
                                id: st_delay
                                active: True
                            Label:
                                text: "Adicionar delay inicial de 10 min"
                                halign: "left"; valign: "middle"
                                text_size: self.size

                        BoxLayout:
                            size_hint_y: None
                            height: dp(42)
                            spacing: dp(8)
                            Button:
                                text: "Calcular"
                                on_release: app.on_stamina_calc()
                            Button:
                                text: "Copiar resultado"
                                on_release: app.copy(app.st_out)

                        Label:
                            text: app.st_out
                            markup: True

<FavRow@BoxLayout>:
    size_hint_y: None
    height: dp(46)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: (0.95,0.95,0.97,1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [12,]

    Label:
        text: root.name
        halign: "left"
        valign: "middle"
        text_size: self.size

    Button:
        text: "Remover"
        size_hint_x: None
        width: dp(110)
        on_release: app.on_remove_favorite(root.name)
'''

class TibiaToolsApp(App):
    favorites = ListProperty([])
    last_snapshot_text = StringProperty("")
    status_text = StringProperty("Monitor: OFF")
    max_favorites = NumericProperty(MAX_FAVORITES)
    interval_seconds = NumericProperty(60)
    monitoring = BooleanProperty(False)

    # outputs utilities
    bless_out = StringProperty("")
    rashid_out = StringProperty("")
    ss_out = StringProperty("")
    st_out = StringProperty("")

    # cfg values mirrored in properties
    bless_cfg_threshold = NumericProperty(120)
    bless_cfg_regular_base = NumericProperty(20000)
    bless_cfg_regular_step = NumericProperty(75)
    bless_cfg_enhanced_base = NumericProperty(26000)
    bless_cfg_enhanced_step = NumericProperty(100)
    bless_cfg_twist = NumericProperty(20000)
    bless_cfg_inq_discount = NumericProperty(10)

    def on_start(self):
        # Force portrait on Android (even if buildozer spec is wrong)
        self._force_portrait_android()

    def _force_portrait_android(self):
        if platform != "android":
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ActivityInfo = autoclass("android.content.pm.ActivityInfo")
            activity = PythonActivity.mActivity
            activity.setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT)
        except Exception:
            # Don't crash if JNI is unavailable
            pass

    def _crash_log_path(self) -> str:
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(self.user_data_dir, "crash.log")

    def _write_crash(self, exc: Exception):
        try:
            with open(self._crash_log_path(), "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 72 + "\n")
                f.write(datetime.now().isoformat(timespec="seconds") + " - Uncaught Exception\n")
                f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except Exception:
            pass

    def _error_root(self, exc: Exception):
        # Minimal UI so you can see the error on-device (instead of “abre e fecha”)
        box = BoxLayout(orientation="vertical", padding=20, spacing=12)
        box.add_widget(Label(text="[b]Falha ao iniciar[/b]", markup=True, size_hint_y=None, height=40))
        box.add_widget(Label(text="O app gravou um crash.log em:", size_hint_y=None, height=26))
        box.add_widget(Label(text=self.user_data_dir, size_hint_y=None, height=26))
        sv = ScrollView()
        lbl = Label(text="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                    text_size=(None, None), size_hint=(1, None), markup=False)
        # allow wrapping
        lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
        lbl.bind(texture_size=lambda inst, ts: setattr(inst, "height", ts[1]))
        sv.add_widget(lbl)
        box.add_widget(sv)
        return box

    def build(self):
        try:
            root = Builder.load_string(KV)
            self._root = root

            st = load_state(self.user_data_dir)
            self.favorites = st.get("favorites", [])
            self.interval_seconds = int(st.get("interval_seconds", 60))
            self.monitoring = bool(st.get("monitoring", False))
            self.status_text = "Monitor: ON" if self.monitoring else "Monitor: OFF"

            cfg = st.get("bless_cfg", {})
            self.bless_cfg_threshold = int(cfg.get("threshold_level", 120))
            self.bless_cfg_regular_base = int(cfg.get("regular_base", 20000))
            self.bless_cfg_regular_step = int(cfg.get("regular_step", 75))
            self.bless_cfg_enhanced_base = int(cfg.get("enhanced_base", 26000))
            self.bless_cfg_enhanced_step = int(cfg.get("enhanced_step", 100))
            self.bless_cfg_twist = int(cfg.get("twist_cost", 20000))
            self.bless_cfg_inq_discount = int(cfg.get("inq_discount_pct", 10))

            if platform == "android":
                try:
                    from android.permissions import request_permissions, Permission
                    request_permissions([Permission.POST_NOTIFICATIONS])
                except Exception:
                    pass

            Clock.schedule_once(lambda *_: self._refresh_list(), 0)
            Clock.schedule_interval(lambda *_: self._tick_rashid(), 1.0)
            Clock.schedule_once(lambda *_: self.update_rashid_and_ss(), 0)

            # initial outputs
            self.on_bless_calc()
            self.on_stamina_calc()
            return root


        except Exception as e:
            self._write_crash(e)
            return self._error_root(e)

    def go(self, name: str):
        self._root.ids.sm.current = name

    def _refresh_list(self):
        self._root.ids.fav_list.data = [{"name": n} for n in self.favorites]

    # ---------------- Favorites ----------------
    def on_add_favorite(self, name: str):
        name = (name or "").strip()
        if not name:
            return
        ok, msg, new_list = add_favorite(self.user_data_dir, name)
        self.favorites = new_list
        self._refresh_list()
        self.notify("Favoritos", msg if not ok else f"Adicionado: {name}")

    def on_remove_favorite(self, name: str):
        ok, msg, new_list = remove_favorite(self.user_data_dir, name)
        self.favorites = new_list
        self._refresh_list()
        self.notify("Favoritos", msg)

    def on_interval_change(self, val: str):
        try:
            self.interval_seconds = int(val)
        except Exception:
            self.interval_seconds = 60
        st = load_state(self.user_data_dir)
        st["interval_seconds"] = self.interval_seconds
        save_state(self.user_data_dir, st)

    def on_toggle_monitor(self, enabled: bool):
        self.monitoring = enabled
        self.status_text = "Monitor: ON" if enabled else "Monitor: OFF"
        st = load_state(self.user_data_dir)
        st["monitoring"] = enabled
        save_state(self.user_data_dir, st)

        if platform == "android":
            if enabled:
                self._start_service()
            else:
                self._stop_service()
        else:
            self.notify("Info", "Monitor foreground só funciona no Android (APK).")

    def _start_service(self):
        try:
            from android import AndroidService
            svc = AndroidService("Tibia Tools", "Monitorando favoritos…")
            payload = json.dumps({"user_data_dir": self.user_data_dir, "interval": int(self.interval_seconds)})
            svc.start(payload)
            self.notify("Monitor", "Serviço iniciado (foreground).")
        except Exception as e:
            self.notify("Erro", f"Falha ao iniciar serviço: {e}")

    def _stop_service(self):
        try:
            from android import AndroidService
            svc = AndroidService("Tibia Tools", "Monitorando favoritos…")
            svc.stop()
            self.notify("Monitor", "Serviço parado.")
        except Exception as e:
            self.notify("Erro", f"Falha ao parar serviço: {e}")

    def notify(self, title: str, message: str):
        if platform == "android":
            try:
                from plyer import notification
                notification.notify(title=title, message=message, app_name="Tibia Tools")
                return
            except Exception:
                pass
        print(f"[NOTIFY] {title}: {message}")

    def on_snapshot(self):
        if not self.favorites:
            self.last_snapshot_text = "Adicione um favorito primeiro."
            return
        name = self.favorites[0]
        try:
            snap = fetch_character_snapshot(name, timeout=10)
            self.last_snapshot_text = f"{name}: lvl {snap.get('level','-')} | online={snap.get('online','?')} | deaths={len(snap.get('deaths',[]))}"
        except Exception as e:
            self.last_snapshot_text = f"Erro snapshot: {e}"

    # ---------------- Utilities: Blessings ----------------
    def _get_cfg(self) -> BlessConfig:
        return BlessConfig(
            threshold_level=int(self.bless_cfg_threshold),
            regular_base=int(self.bless_cfg_regular_base),
            regular_step=int(self.bless_cfg_regular_step),
            enhanced_base=int(self.bless_cfg_enhanced_base),
            enhanced_step=int(self.bless_cfg_enhanced_step),
            twist_cost=int(self.bless_cfg_twist),
            inq_discount_pct=int(self.bless_cfg_inq_discount),
        )

    def on_bless_changed(self):
        # placeholder if want live calc
        pass

    def on_bless_calc(self):
        try:
            lvl = int(self._root.ids.bl_level.text or "1")
        except Exception:
            lvl = 1
        reg = int(self._root.ids.bl_reg.text)
        enh = int(self._root.ids.bl_enh.text)

        world = self._root.ids.bl_world.text
        twist_active = bool(self._root.ids.bl_twist.active)
        if world == "Retro Open PvP":
            twist_active = False
            self._root.ids.bl_twist.active = False

        inq = bool(self._root.ids.bl_inq.active)

        out = calc_blessings(lvl, reg, enh, twist_active, inq, self._get_cfg())
        total = out["total"]
        reg_each = out["regular_each"]
        enh_each = out["enhanced_each"]
        disc = out["discount_amt"]

        lines = []
        lines.append(f"[b]Total:[/b] {total:,} gp")
        lines.append(f"Regulares: {reg} × {reg_each:,} = {out['breakdown']['regular']:,} gp")
        lines.append(f"Enhanced: {enh} × {enh_each:,} = {out['breakdown']['enhanced']:,} gp")
        lines.append(f"Twist: {out['breakdown']['twist']:,} gp")
        if disc:
            lines.append(f"Desconto Inq.: -{disc:,} gp")
        if world == "Retro Open PvP":
            lines.append("[i]Obs: Retro Open PvP não permite Twist.[/i]")
        lines.append("[i]Obs: custos são configuráveis (podem mudar com updates).[/i]")
        self.bless_out = "\n".join(lines)

    def toggle_bless_cfg(self):
        box = self._root.ids.bless_cfg_box
        if box.height == 0:
            box.height = box.minimum_height
            box.opacity = 1
        else:
            box.height = 0
            box.opacity = 0

    def save_bless_cfg(self):
        # lê do form e salva no state
        try:
            self.bless_cfg_threshold = int(self._root.ids.cfg_thr.text or "120")
            self.bless_cfg_regular_base = int(self._root.ids.cfg_reg_base.text or "20000")
            self.bless_cfg_regular_step = int(self._root.ids.cfg_reg_step.text or "75")
            self.bless_cfg_enhanced_base = int(self._root.ids.cfg_enh_base.text or "26000")
            self.bless_cfg_enhanced_step = int(self._root.ids.cfg_enh_step.text or "100")
            self.bless_cfg_twist = int(self._root.ids.cfg_twist.text or "20000")
            self.bless_cfg_inq_discount = int(self._root.ids.cfg_inq.text or "10")
        except Exception:
            self.notify("Blessings", "Valores inválidos na configuração.")
            return

        st = load_state(self.user_data_dir)
        st["bless_cfg"] = {
            "threshold_level": int(self.bless_cfg_threshold),
            "regular_base": int(self.bless_cfg_regular_base),
            "regular_step": int(self.bless_cfg_regular_step),
            "enhanced_base": int(self.bless_cfg_enhanced_base),
            "enhanced_step": int(self.bless_cfg_enhanced_step),
            "twist_cost": int(self.bless_cfg_twist),
            "inq_discount_pct": int(self.bless_cfg_inq_discount),
        }
        save_state(self.user_data_dir, st)
        self.notify("Blessings", "Custos salvos.")
        self.on_bless_calc()

    # ---------------- Utilities: Rashid + Server Save ----------------
    def _tick_rashid(self):
        # Atualiza só o timer a cada 1s
        self._update_server_save_only()

    def update_rashid_and_ss(self):
        r = rashid_today()
        self.rashid_out = f"[b]Rashid hoje:[/b] {r['city']}\n[i]{r['where']}[/i]"
        self._update_server_save_only()

    def _update_server_save_only(self):
        try:
            nxt = next_server_save_utc()
            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            delta = nxt - now
            sec = int(delta.total_seconds())
            if sec < 0:
                sec = 0
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            cet = to_cet(nxt)
            local = __import__("datetime").datetime.fromtimestamp(nxt.timestamp())
            self.ss_out = (f"[b]Server Save em:[/b] {h:02d}:{m:02d}:{s:02d}\n"
                           f"CET/CEST: {cet.strftime('%Y-%m-%d %H:%M')}\n"
                           f"Local: {local.strftime('%Y-%m-%d %H:%M')}")
        except Exception:
            self.ss_out = "[b]Server Save em:[/b] -"

    # ---------------- Utilities: Stamina ----------------
    def on_stamina_calc(self):
        cur = self._root.ids.st_cur.text
        tgt = self._root.ids.st_tgt.text
        delay = bool(self._root.ids.st_delay.active)
        try:
            out = calc_stamina_offline(cur, tgt, delay)
            self.st_out = ("[b]Resultado[/b]\n"
                           f"Atual: {out['current']}  |  Meta: {out['target']}\n"
                           f"Até 39:00: {out['offline_to_39']}\n"
                           f"Até 42:00: {out['offline_to_42']}\n"
                           f"Até a meta: {out['offline_to_target']}\n"
                           f"[i]{out['note']}[/i]")
        except Exception as e:
            self.st_out = f"[b]Erro:[/b] {e}"

    def copy(self, text: str):
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(text.replace('[b]','').replace('[/b]','').replace('[i]','').replace('[/i]',''))
            self.notify("Copiado", "Resultado copiado para a área de transferência.")
        except Exception:
            pass

if __name__ == "__main__":
    TibiaToolsApp().run()
