""" 
Text Expander - Expansor de Snippets para Windows com System Tray
Versão: 2.6 (snippets de ações em thread + JSON na mesma pasta + GUI de snippets)
Autor: Desenvolvido para uso pessoal legítimo

IMPORTANTE: Este programa captura entrada de teclado apenas para expandir
snippets de texto (atalhos), similar ao TextExpander. Não armazena, transmite
ou registra teclas digitadas. Todo o processamento é local.

Bibliotecas usadas: 
- pynput (open source, LGPL, mantida desde 2015)
- pystray (open source, LGPL)
- pillow (open source, PIL License)
- yfinance (open source, Apache 2.0)
"""

import time
import json
import os
import ctypes
import threading
import subprocess

from pynput import keyboard
from pynput.keyboard import Controller, Key
import pystray
from PIL import Image, ImageDraw, ImageFont

from bcb_consultor import BCBConsultor
from yf_stocks import B3FundamentosConsultor

# GUI para gerenciar snippets
import tkinter as tk
from tkinter import ttk, messagebox


class TextExpander:
    def __init__(self, snippets_file: str = 'snippets.json'):
        self.keyboard_controller = Controller()
        self.typed_text = ""
        self.expansion_failed = False
        self.last_expansion_time = 0
        self.enabled = True
        self.icon = None
        self.listener = None

        # Sempre usa o JSON na mesma pasta do arquivo .py
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.snippets_file = os.path.join(self.base_dir, snippets_file)
        print(f"➡ Arquivo de snippets configurado para: {self.snippets_file}")

        # Inicializa o consultor de ações B3/US
        self.b3_consultor = B3FundamentosConsultor(cache_seconds=600)
        
        # Carrega snippets antes de qualquer outra coisa
        self.snippets = self.load_snippets()
        self.max_trigger_length = max(len(trigger) for trigger in self.snippets.keys()) if self.snippets else 20

        # Snippets de ações (lentos: pedem ticker + consulta)
        self.slow_snippets = {
            "xcot", "xplucro", "xcap", "xpvp", "xdy",
            "xebt", "xmarg", "xroe", "xdivl", "xdivt",
            "xcaixa", "xvol", "xrec", "xbeta", "x52w",
            "xfund"
        }
    
    # =====================================================================
    # CARREGAMENTO E SALVAMENTO DE SNIPPETS
    # =====================================================================

    def is_admin(self):
        """Verifica se o programa está rodando como administrador"""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False
    
    def load_snippets(self):
        """Carrega snippets do arquivo JSON e adiciona os dinâmicos"""
        print(f"➡ Usando arquivo de snippets: {os.path.abspath(self.snippets_file)}")

        if os.path.exists(self.snippets_file):
            try:
                with open(self.snippets_file, 'r', encoding='utf-8') as f:
                    static_snippets = json.load(f)
                if not isinstance(static_snippets, dict):
                    print("⚠ Formato inesperado em snippets.json, usando defaults.")
                    static_snippets = self.get_default_snippets()
                print(f"✓ Snippets carregados do arquivo: {len(static_snippets)} snippets")
            except Exception as e:
                print(f"⚠ Erro ao carregar snippets: {e}")
                static_snippets = self.get_default_snippets()
                self.save_snippets(static_snippets)
        else:
            print("ℹ Primeira execução: criando arquivo de snippets padrão")
            static_snippets = self.get_default_snippets()
            self.save_snippets(static_snippets)
        
        # Adiciona snippets dinâmicos
        dynamic_snippets = self.get_dynamic_snippets()
        
        # Mescla: snippets do JSON + dinâmicos (dinâmicos têm prioridade)
        all_snippets = {**static_snippets, **dynamic_snippets}
        
        print(f"✓ Total de snippets: {len(all_snippets)} ({len(static_snippets)} estáticos + {len(dynamic_snippets)} dinâmicos)")
        
        return all_snippets
    
    def get_default_snippets(self):
        """Retorna snippets padrão de exemplo (apenas estáticos para o JSON)"""
        return {
            "xname": "Project Contributors",
            
            "_cnpj_numbers": {
                "empresa1": "12.345.678/0001-90",
                "empresa2": "98.765.432/0001-10",
            },
            "_cpf_numbers": {
                "fulano": "123.456.789-00",
            }
        }
    
    def save_snippets(self, snippets: dict):
        """Salva apenas snippets estáticos no arquivo JSON"""
        saveable = {k: v for k, v in snippets.items() if not callable(v)}
        try:
            with open(self.snippets_file, 'w', encoding='utf-8') as f:
                json.dump(saveable, f, ensure_ascii=False, indent=2)
            print("✓ snippets.json salvo com sucesso.")
        except Exception as e:
            print(f"Erro ao salvar snippets: {e}")

    # =====================================================================
    # UTILITÁRIOS DE DATA / TEXTO / INPUT
    # =====================================================================

    def data_extenso(self):
        """Retorna a data por extenso em português"""
        dias = ['segunda-feira', 'terça-feira', 'quarta-feira', 
                'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
        meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
        
        now = time.localtime()
        dia_semana = dias[now.tm_wday]
        dia = now.tm_mday
        mes = meses[now.tm_mon - 1]
        ano = now.tm_year
        
        return f"{dia_semana}, {dia:02d} de {mes} de {ano}"
    
    def ask_ticker_input(self, prompt_title: str):
        """
        Pede o ticker usando VBScript (nativo do Windows).
        Roda bem em thread separada.
        """
        print(f"📊 Abrindo input para {prompt_title}...")
        
        try:
            # Script VBS
            vbs_script = f'''userInput = InputBox("Digite o ticker:" & vbCrLf & "Ex: PETR4, AAPL, MSFT", "{prompt_title}", "")
If userInput <> "" Then WScript.Echo userInput'''

            # Tenta via mshta
            result = subprocess.run(
                ['mshta', 'vbscript:Execute("' + vbs_script.replace('"', '""') + '(Close)")'],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if not result.stdout.strip():
                # Fallback via arquivo VBS + cscript
                vbs_file = os.path.join(os.environ.get('TEMP', '.'), 'txtexp_input.vbs')
                with open(vbs_file, 'w', encoding='utf-8') as f:
                    f.write(vbs_script)
                
                result = subprocess.run(
                    ['cscript', '//nologo', vbs_file],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                try:
                    os.remove(vbs_file)
                except Exception:
                    pass
            
            ticker = result.stdout.strip()
            
            if ticker:
                ticker = ticker.upper()
                print(f"✓ Ticker digitado: {ticker}")
                return ticker
            else:
                print("⚠ Cancelado ou vazio")
                return None
                
        except subprocess.TimeoutExpired:
            print("⚠ Timeout no dialog")
            return None
        except Exception as e:
            print(f"⚠ Erro no dialog: {e}")
            return None

    # =====================================================================
    # SNIPPETS DINÂMICOS (datas, BCB, ações)
    # =====================================================================

    def get_dynamic_snippets(self):
        """Retorna snippets dinâmicos (data/hora/BCB/ações) que não vão para o JSON"""
        bcb = BCBConsultor(timeout=3, cache_seconds=300)
        
        return {
            # Data e hora - expandem instantaneamente
            "x-hj": lambda: time.strftime("%Y-%m-%d"),
            "xhj": lambda: time.strftime("%d/%m/%Y"),
            "xhoje": self.data_extenso,
            "xnow": lambda: time.strftime("%H:%M:%S"),
            "xdatahora": lambda: time.strftime("%d/%m/%Y às %H:%M"),
            
            # Indicadores econômicos (Banco Central)
            "xdolar": bcb.get_dolar,
            "xselic": bcb.get_selic_meta,
            "xipcam": bcb.get_ipca_mensal,
            "xipca12": bcb.get_ipca_12m,
            "xcdi": bcb.get_cdi,
            "xptax": bcb.get_ptax_sgs,
            "xeconomia": bcb.get_resumo_economico,
            
            # Snippets de ações (tratados como lentos no listener)
            "xcot": self.snippet_cotacao,
            "xplucro": self.snippet_preco_lucro,
            "xcap": self.snippet_market_cap,
            "xpvp": self.snippet_preco_vp,
            "xdy": self.snippet_dividend_yield,
            "xebt": self.snippet_ebitda,
            "xmarg": self.snippet_margem_liquida,
            "xroe": self.snippet_roe,
            "xdivl": self.snippet_divida_liquida,
            "xdivt": self.snippet_divida_total,
            "xcaixa": self.snippet_caixa,
            "xvol": self.snippet_volume_medio,
            "xrec": self.snippet_receita_liquida,
            "xbeta": self.snippet_beta,
            "x52w": self.snippet_52week,
            "xfund": self.snippet_resumo_fundamentos,
        }
    
    # =====================================================================
    # SNIPPETS DE AÇÕES (usados pelos lentos)
    # =====================================================================

    def snippet_cotacao(self):
        print("📊 Snippet xcot acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Cotação")
        if ticker:
            print(f"🔍 Buscando cotação para {ticker}...")
            result = self.b3_consultor.get_cotacao_atual(ticker)
            print(f"✓ Resultado: {result}")
            return result
        return "[Cancelado]"
    
    def snippet_preco_lucro(self):
        print("📊 Snippet xplucro acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("P/L")
        if ticker:
            return self.b3_consultor.get_preco_lucro(ticker)
        return "[Cancelado]"
    
    def snippet_market_cap(self):
        print("📊 Snippet xcap acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Market Cap")
        if ticker:
            return self.b3_consultor.get_market_cap(ticker)
        return "[Cancelado]"
    
    def snippet_preco_vp(self):
        print("📊 Snippet xpvp acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("P/VP")
        if ticker:
            return self.b3_consultor.get_preco_vp(ticker)
        return "[Cancelado]"
    
    def snippet_dividend_yield(self):
        print("📊 Snippet xdy acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Dividend Yield")
        if ticker:
            return self.b3_consultor.get_dividend_yield(ticker)
        return "[Cancelado]"
    
    def snippet_ebitda(self):
        print("📊 Snippet xebt acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("EBITDA")
        if ticker:
            return self.b3_consultor.get_ebitda(ticker)
        return "[Cancelado]"
    
    def snippet_margem_liquida(self):
        print("📊 Snippet xmarg acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Margem Líquida")
        if ticker:
            return self.b3_consultor.get_margem_liquida(ticker)
        return "[Cancelado]"
    
    def snippet_roe(self):
        print("📊 Snippet xroe acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("ROE")
        if ticker:
            return self.b3_consultor.get_roe(ticker)
        return "[Cancelado]"
    
    def snippet_divida_liquida(self):
        print("📊 Snippet xdiv acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Dívida Líquida")
        if ticker:
            result = self.b3_consultor.get_divida_liquida(ticker)
            return result
        return "[Cancelado]"

    def snippet_divida_total(self):
        print("📊 Snippet xdivt acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Dívida Total")
        if ticker:
            result = self.b3_consultor.get_divida_total(ticker)
            return result
        return "[Cancelado]"

    def snippet_caixa(self):
        print("📊 Snippet xcaixa acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Caixa")
        if ticker:
            result = self.b3_consultor.get_caixa(ticker)
            return result
        return "[Cancelado]"
    
    def snippet_volume_medio(self):
        print("📊 Snippet xvol acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Volume Médio")
        if ticker:
            return self.b3_consultor.get_volume_medio(ticker)
        return "[Cancelado]"
    
    def snippet_receita_liquida(self):
        ticker = self.ask_ticker_input("Receita Líquida")
        return self.b3_consultor.get_receita_liquida(ticker) if ticker else "[Cancelado]"

    def snippet_beta(self):
        ticker = self.ask_ticker_input("Beta")
        return self.b3_consultor.get_beta(ticker) if ticker else "[Cancelado]"

    def snippet_52week(self):
        ticker = self.ask_ticker_input("52 Semanas High/Low")
        return self.b3_consultor.get_52week_high_low(ticker) if ticker else "[Cancelado]"
    
    def snippet_resumo_fundamentos(self):
        print("📊 Snippet xfund acionado - abrindo dialog...")
        ticker = self.ask_ticker_input("Resumo de Fundamentos")
        if ticker:
            print(f"🔍 Buscando resumo para {ticker}...")
            return self.b3_consultor.get_resumo_fundamentos(ticker)
        return "[Cancelado]"

    # =====================================================================
    # PADRÕES ESPECIAIS (cnpj/cpf/cge)
    # =====================================================================

    def get_all_dynamic_prefixes(self):
        """Retorna todos os prefixos de mapeamentos dinâmicos (padrão + customizados)"""
        prefixes = {}
        
        # Padrões built-in
        builtin = {
            "_cpf_numbers": "cpf",
            "_cnpj_numbers": "cnpj",
        }
        
        for map_key, prefix in builtin.items():
            if map_key in self.snippets:
                prefixes[prefix] = map_key
        
        # Customizados (terminam com _numbers ou _codes)
        for key in self.snippets.keys():
            if key.startswith("_") and key.endswith(("_numbers", "_codes")) and key not in builtin:
                mapping = self.snippets[key]
                # Usa prefixo customizado se armazenado, senão deriva do nome da chave
                if isinstance(mapping, dict) and "__prefix__" in mapping:
                    prefix = mapping["__prefix__"]
                else:
                    prefix = key[1:].replace("_numbers", "").replace("_codes", "")
                prefixes[prefix] = key
        
        return prefixes

    def check_dynamic_pattern(self, text: str):
        """Verifica se o texto corresponde a um padrão dinâmico (cnpj/cpf/cge/customizados)"""
        
        prefixes = self.get_all_dynamic_prefixes()
        
        for prefix, mapping_key in prefixes.items():
            if text.startswith(prefix) and len(text) > len(prefix):
                nome = text[len(prefix):]
                
                if mapping_key in self.snippets:
                    mapping = self.snippets[mapping_key]
                    if isinstance(mapping, dict) and nome in mapping and nome != "__prefix__":
                        return mapping[nome], len(text)
        
        return None, 0

    # =====================================================================
    # EXPANSÃO DE SNIPPETS
    # =====================================================================

    def _paste_via_clipboard(self, text: str):
        """
        Paste text using Windows clipboard + Ctrl+V.
        More reliable than keyboard.type() for text containing newlines,
        and works correctly in chat apps (WhatsApp, Discord, Teams)
        where simulating Enter would send the message instead.
        Saves and restores the previous clipboard content.
        """
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # Must set restype explicitly — default c_int truncates 64-bit pointers
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        def _set_clip(content):
            encoded = (content + '\0').encode('utf-16-le')
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            ptr = kernel32.GlobalLock(h)
            ctypes.memmove(ptr, encoded, len(encoded))
            kernel32.GlobalUnlock(h)
            user32.OpenClipboard(0)
            user32.EmptyClipboard()
            user32.SetClipboardData(CF_UNICODETEXT, h)
            user32.CloseClipboard()

        def _get_clip():
            try:
                user32.OpenClipboard(0)
                h = user32.GetClipboardData(CF_UNICODETEXT)
                if not h:
                    return None
                ptr = kernel32.GlobalLock(h)
                result = ctypes.wstring_at(ptr)
                kernel32.GlobalUnlock(ctypes.c_void_p(ptr))
                return result
            except Exception:
                return None
            finally:
                try:
                    user32.CloseClipboard()
                except Exception:
                    pass

        old_content = _get_clip()
        _set_clip(text)
        time.sleep(0.05)
        with self.keyboard_controller.pressed(Key.ctrl):
            self.keyboard_controller.press('v')
            self.keyboard_controller.release('v')

        if old_content is not None:
            def restore():
                time.sleep(0.5)
                try:
                    _set_clip(old_content)
                except Exception:
                    pass
            threading.Thread(target=restore, daemon=True).start()

    def expand_snippet(self, trigger: str):
        """
        Expande o snippet correspondente ao trigger (versão original).
        Usado para snippets "normais" (não lentos).
        """
        if not self.enabled:
            return False
        
        # Não roda snippet lento aqui (eles vão pela thread)
        if trigger in self.slow_snippets:
            return False
            
        snippet = None
        
        if trigger in self.snippets:
            snippet = self.snippets[trigger]
            if callable(snippet):
                snippet = snippet()
        else:
            snippet, _ = self.check_dynamic_pattern(trigger)
        
        if snippet is not None:
            try:
                for _ in range(len(trigger)):
                    self.keyboard_controller.press(Key.backspace)
                    self.keyboard_controller.release(Key.backspace)
                    time.sleep(0.01)
                
                time.sleep(0.05)
                self._paste_via_clipboard(str(snippet))

                self.expansion_failed = False
                self.last_expansion_time = time.time()
                return True
                
            except Exception as e:
                current_time = time.time()
                if not self.expansion_failed or (current_time - self.last_expansion_time) > 5:
                    print(f"\n⚠️  AVISO: Não foi possível expandir o snippet!")
                    print(f"   Motivo: {str(e)}")
                    print(f"   Solução: Execute como administrador ou use em aplicativos normais\n")
                    self.expansion_failed = True
                    self.last_expansion_time = current_time
                return False
        return False

    def run_slow_snippet(self, trigger: str):
        """
        Executa snippets 'pesados' (ações) em thread separada:
        - abre popup
        - consulta dados
        - digita resultado
        """
        try:
            func = self.snippets.get(trigger)
            if not callable(func):
                return
            result = func()
            if not result:
                return
            time.sleep(0.05)
            self._paste_via_clipboard(str(result))
        except Exception as e:
            print(f"Erro ao executar snippet lento {trigger}: {e}")
    
    # =====================================================================
    # LISTENER DE TECLADO
    # =====================================================================

    def on_press(self, key):
        """Callback chamado quando uma tecla é pressionada - VERSÃO ATUALIZADA"""
        try:
            if hasattr(key, 'char') and key.char:
                self.typed_text += key.char
                
                if len(self.typed_text) > self.max_trigger_length:
                    self.typed_text = self.typed_text[-self.max_trigger_length:]
                
                expanded = False

                # 1) Snippets diretos
                for trigger in self.snippets.keys():
                    if trigger.startswith("_"):
                        continue
                    if self.typed_text.endswith(trigger):
                        if trigger in self.slow_snippets:
                            for _ in range(len(trigger)):
                                self.keyboard_controller.press(Key.backspace)
                                self.keyboard_controller.release(Key.backspace)
                                time.sleep(0.01)
                            self.typed_text = ""
                            threading.Thread(
                                target=self.run_slow_snippet,
                                args=(trigger,),
                                daemon=True
                            ).start()
                            expanded = True
                            break
                        else:
                            self.expand_snippet(trigger)
                            self.typed_text = ""
                            expanded = True
                            break
                
                # 2) Padrões dinâmicos (ATUALIZADO para pegar prefixes customizados)
                if not expanded:
                    prefixes = self.get_all_dynamic_prefixes()
                    
                    for prefix in prefixes.keys():
                        if prefix in self.typed_text:
                            prefix_start = self.typed_text.rfind(prefix)
                            potential_trigger = self.typed_text[prefix_start:]
                            
                            result, trigger_len = self.check_dynamic_pattern(potential_trigger)
                            if result:
                                self.expand_snippet(potential_trigger)
                                self.typed_text = ""
                                break
                                
        except AttributeError:
            if key == Key.enter:
                self.typed_text = ""
            elif key == Key.backspace and self.typed_text:
                self.typed_text = self.typed_text[:-1]

    # =====================================================================
    # GUI PARA GERENCIAR SNIPPETS
    # =====================================================================

    def manage_snippets_gui(self, icon, item):
        """Abre GUI completa para gerenciar snippets estáticos e mapeamentos dinâmicos."""
        threading.Thread(target=self._manage_snippets_gui_thread, daemon=True).start()

    def _manage_snippets_gui_thread(self):
        """Thread que roda a janela tkinter de gerenciamento completo."""
        try:
            root = tk.Tk()
            root.title("Gerenciar Snippets - Text Expander")
            root.geometry("700x500")
            root.resizable(False, False)

            # ===================================================================
            # NOTEBOOK (ABAS)
            # ===================================================================
            notebook = ttk.Notebook(root)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # ABA 1: Snippets Estáticos
            tab_static = tk.Frame(notebook)
            notebook.add(tab_static, text="Snippets Estáticos")

            # ABA 2: Mapeamentos Dinâmicos
            tab_dynamic = tk.Frame(notebook)
            notebook.add(tab_dynamic, text="Mapeamentos Dinâmicos")

            # ABA 3: Data/Hora & Economia
            tab_datetime_eco = tk.Frame(notebook)
            notebook.add(tab_datetime_eco, text="Data/Hora & Economia")

            # ABA 4: Ações (Stocks)
            tab_stocks = tk.Frame(notebook)
            notebook.add(tab_stocks, text="Ações (Stocks)")

            # ===================================================================
            # ABA 1: SNIPPETS ESTÁTICOS
            # ===================================================================
            self._create_static_snippets_tab(tab_static, root)

            # ===================================================================
            # ABA 2: MAPEAMENTOS DINÂMICOS
            # ===================================================================
            self._create_dynamic_mappings_tab(tab_dynamic, root)

            # ===================================================================
            # ABA 3: DATA/HORA & ECONOMIA
            # ===================================================================
            self._create_datetime_eco_tab(tab_datetime_eco)

            # ===================================================================
            # ABA 4: AÇÕES (STOCKS)
            # ===================================================================
            self._create_stocks_tab(tab_stocks)

            root.mainloop()

        except Exception as e:
            print(f"Erro na GUI de gerenciamento: {e}")

    def _create_static_snippets_tab(self, parent, root):
        """Cria a interface da aba de snippets estáticos."""
        
        # Frame esquerdo - Lista
        frame_left = tk.Frame(parent)
        frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)

        tk.Label(frame_left, text="Snippets estáticos", font=("Arial", 10, "bold")).pack(anchor="w")

        listbox = tk.Listbox(frame_left, width=25, height=20)
        listbox.pack(side=tk.LEFT, fill=tk.Y, pady=5)

        scrollbar = tk.Scrollbar(frame_left, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)

        # Frame direito - Edição
        frame_right = tk.Frame(parent)
        frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(frame_right, text="Trigger:", font=("Arial", 9)).pack(anchor="w")
        entry_trigger = tk.Entry(frame_right, font=("Arial", 10))
        entry_trigger.pack(fill=tk.X, pady=(0, 10))

        tk.Label(frame_right, text="Valor do snippet:", font=("Arial", 9)).pack(anchor="w")
        text_value = tk.Text(frame_right, wrap=tk.WORD, height=12, font=("Arial", 10))
        text_value.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Botões
        btn_frame = tk.Frame(frame_right)
        btn_frame.pack(fill=tk.X)

        btn_new = tk.Button(btn_frame, text="Novo", width=12)
        btn_save = tk.Button(btn_frame, text="Salvar", width=12)
        btn_delete = tk.Button(btn_frame, text="Excluir", width=12)

        btn_new.pack(side=tk.LEFT, padx=3)
        btn_save.pack(side=tk.LEFT, padx=3)
        btn_delete.pack(side=tk.LEFT, padx=3)

        # Funções
        def get_static_visible_snippets():
            return {
                k: v for k, v in self.snippets.items()
                if (not k.startswith("_")) and (not callable(v))
            }

        static_snips = get_static_visible_snippets()

        def refresh_listbox():
            listbox.delete(0, tk.END)
            static_snips.clear()
            static_snips.update(get_static_visible_snippets())
            for key in sorted(static_snips.keys()):
                listbox.insert(tk.END, key)

        def load_selected(event=None):
            selection = listbox.curselection()
            if not selection:
                return
            key = listbox.get(selection[0])
            entry_trigger.delete(0, tk.END)
            entry_trigger.insert(0, key)
            text_value.delete("1.0", tk.END)
            text_value.insert(tk.END, str(static_snips.get(key, "")))

        def on_new():
            entry_trigger.delete(0, tk.END)
            text_value.delete("1.0", tk.END)
            entry_trigger.focus_set()

        def on_save():
            trigger = entry_trigger.get().strip()
            value = text_value.get("1.0", tk.END).rstrip("\n")

            if not trigger:
                messagebox.showwarning("Aviso", "Informe um trigger.")
                return
            if trigger.startswith("_"):
                messagebox.showwarning("Aviso", "Triggers com '_' são reservados.")
                return

            self.snippets[trigger] = value
            self.save_snippets(self.snippets)
            self.max_trigger_length = max(len(t) for t in self.snippets.keys()) if self.snippets else 20

            messagebox.showinfo("Sucesso", f"Snippet '{trigger}' salvo.")
            refresh_listbox()

        def on_delete():
            trigger = entry_trigger.get().strip()
            if not trigger:
                messagebox.showwarning("Aviso", "Selecione um snippet.")
                return

            if trigger in self.snippets:
                if messagebox.askyesno("Confirmar", f"Excluir '{trigger}'?"):
                    del self.snippets[trigger]
                    self.save_snippets(self.snippets)
                    self.max_trigger_length = max(len(t) for t in self.snippets.keys()) if self.snippets else 20
                    entry_trigger.delete(0, tk.END)
                    text_value.delete("1.0", tk.END)
                    refresh_listbox()

        listbox.bind("<<ListboxSelect>>", load_selected)
        btn_new.configure(command=on_new)
        btn_save.configure(command=on_save)
        btn_delete.configure(command=on_delete)

        refresh_listbox()

    def _create_dynamic_mappings_tab(self, parent, root):
        """Cria interface de mapeamentos dinâmicos com tipos customizáveis - VERSÃO COMPLETA"""
        
        main_container = tk.Frame(parent)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # SEÇÃO 1: TIPOS DE MAPEAMENTO
        frame_types = tk.LabelFrame(main_container, text="Tipos de Mapeamento", font=("Arial", 9, "bold"))
        frame_types.pack(fill=tk.X, pady=(0, 10))
        
        types_inner = tk.Frame(frame_types)
        types_inner.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(types_inner, text="Tipos disponíveis:", font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        
        mapping_type = tk.StringVar(value="_cpf_numbers")
        
        def get_mappings_info():
            """Retorna info de todos os mapeamentos"""
            base = {
                "_cpf_numbers": {"label": "CPF", "prefix": "cpf", "example": "cpffulano → 123.456.789-00", "builtin": True},
                "_cnpj_numbers": {"label": "CNPJ", "prefix": "cnpj", "example": "cnpjempresa1 → 12.345.678/0001-90", "builtin": True},
            }
            
            for key in self.snippets.keys():
                if key.startswith("_") and key.endswith(("_numbers", "_codes")) and key not in base:
                    mapping = self.snippets[key]
                    # Usa prefixo customizado se armazenado, senão deriva do nome da chave
                    if isinstance(mapping, dict) and "__prefix__" in mapping:
                        prefix = mapping["__prefix__"]
                    else:
                        prefix = key[1:].replace("_numbers", "").replace("_codes", "")
                    # Label: nome legível do tipo (sem _ e _codes/_numbers)
                    type_label = key[1:].replace("_numbers", "").replace("_codes", "").upper()
                    base[key] = {
                        "label": type_label,
                        "prefix": prefix,
                        "example": f"{prefix}exemplo → valor",
                        "builtin": False
                    }
            return base
        
        mappings_info = get_mappings_info()
        
        rb_frame = tk.Frame(types_inner)
        rb_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        rb_widgets = []
        
        def refresh_type_radiobuttons():
            nonlocal mappings_info, rb_widgets
            
            for widget in rb_widgets:
                widget.destroy()
            rb_widgets.clear()
            
            mappings_info = get_mappings_info()
            
            for key, info in sorted(mappings_info.items(), key=lambda x: (not x[1]['builtin'], x[1]['label'])):
                rb = tk.Radiobutton(rb_frame, text=info["label"], variable=mapping_type, value=key, font=("Arial", 9))
                rb.pack(side=tk.LEFT, padx=5)
                rb_widgets.append(rb)
        
        btn_types_frame = tk.Frame(types_inner)
        btn_types_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        def add_new_type():
            """Dialog para criar novo tipo"""
            dialog = tk.Toplevel(root)
            dialog.title("Novo Tipo de Mapeamento")
            # NÃO fixa tamanho; deixa o Tk calcular
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()
            
            tk.Label(dialog, text="Criar novo tipo de mapeamento dinâmico", 
                    font=("Arial", 10, "bold")).pack(pady=10)
            
            tk.Label(dialog, text="Nome do tipo (ex: email, telefone, conta):", 
                    font=("Arial", 9)).pack(anchor="w", padx=20, pady=(10, 0))
            entry_type_name = tk.Entry(dialog, font=("Arial", 10))
            entry_type_name.pack(fill=tk.X, padx=20, pady=5)
            
            tk.Label(dialog, text="Prefixo (será usado antes do identificador):", 
                    font=("Arial", 9)).pack(anchor="w", padx=20, pady=(10, 0))
            entry_prefix = tk.Entry(dialog, font=("Arial", 10))
            entry_prefix.pack(fill=tk.X, padx=20, pady=5)
            
            tk.Label(dialog, text="💡 Ex: tipo='email', prefixo='email' → emailtrabalho", 
                    font=("Arial", 8), fg="blue").pack(anchor="w", padx=20, pady=5)
            
            tk.Label(
                dialog,
                text=(
                    "Nota: O prefixo será usado para acionar os valores\n"
                    "ex: emailtrabalho → expandirá o valor cadastrado."
                ),
                font=("Arial", 8),
                fg="gray",
                justify=tk.LEFT
            ).pack(anchor="w", padx=20, pady=5)
            
            def save_new_type():
                type_name = entry_type_name.get().strip().lower()
                prefix = entry_prefix.get().strip().lower()
                
                if not type_name or not prefix:
                    messagebox.showwarning("Aviso", "Preencha todos os campos.", parent=dialog)
                    return
                
                if not type_name.replace("_", "").isalnum() or not prefix.replace("_", "").isalnum():
                    messagebox.showwarning("Aviso", "Use apenas letras, números e underscores.", parent=dialog)
                    return
                
                map_key = f"_{type_name}_codes"
                
                if map_key in self.snippets:
                    messagebox.showwarning("Aviso", f"Tipo '{type_name}' já existe.", parent=dialog)
                    return
                
                # Cria o novo dicionário para o tipo, armazenando o prefixo customizado
                self.snippets[map_key] = {"__prefix__": prefix}
                self.save_snippets(self.snippets)
                
                messagebox.showinfo("Sucesso", f"Tipo '{type_name}' criado com sucesso!", parent=dialog)
                
                # Atualiza radio buttons e seleciona o novo tipo
                refresh_type_radiobuttons()
                mapping_type.set(map_key)
                on_type_changed()
                
                dialog.destroy()
            
            btn_save_type = tk.Button(dialog, text="Criar Tipo", command=save_new_type, width=15)
            btn_save_type.pack(pady=15)
            
            # Ajusta tamanho mínimo e centraliza em relação à janela principal
            dialog.update_idletasks()
            w = dialog.winfo_reqwidth()
            h = dialog.winfo_reqheight()
            x = root.winfo_rootx() + (root.winfo_width() - w) // 2
            y = root.winfo_rooty() + (root.winfo_height() - h) // 2
            dialog.geometry(f"{w}x{h}+{x}+{y}")
            
            entry_type_name.focus_set()

        
        def delete_current_type():
            """Exclui tipo selecionado"""
            current_type = mapping_type.get()
            info = mappings_info.get(current_type, {})
            
            if info.get("builtin", False):
                messagebox.showwarning("Aviso", "Não é possível excluir tipos padrão (CPF, CNPJ).")
                return
            
            if current_type not in self.snippets:
                return
            
            mapping = self.snippets[current_type]
            items_count = len([k for k in mapping if k != "__prefix__"]) if isinstance(mapping, dict) else 0
            
            msg = f"Excluir o tipo '{info['label']}'?"
            if items_count > 0:
                msg += f"\n\nIsso também excluirá {items_count} item(ns) associado(s)."
            
            if messagebox.askyesno("Confirmar Exclusão", msg):
                del self.snippets[current_type]
                self.save_snippets(self.snippets)
                self.max_trigger_length = max(len(t) for t in self.snippets.keys()) if self.snippets else 20
                
                messagebox.showinfo("Sucesso", f"Tipo '{info['label']}' excluído.")
                
                refresh_type_radiobuttons()
                remaining = get_mappings_info()
                if remaining:
                    mapping_type.set(list(remaining.keys())[0])
                    on_type_changed()
        
        btn_add_type = tk.Button(btn_types_frame, text="+ Novo Tipo", command=add_new_type, width=12)
        btn_add_type.pack(side=tk.LEFT, padx=2)
        
        btn_del_type = tk.Button(btn_types_frame, text="✗ Excluir Tipo", command=delete_current_type, width=12)
        btn_del_type.pack(side=tk.LEFT, padx=2)
        
        refresh_type_radiobuttons()
        
        # SEÇÃO 2: ITENS DO MAPEAMENTO
        frame_items = tk.Frame(main_container)
        frame_items.pack(fill=tk.BOTH, expand=True)
        
        frame_list = tk.Frame(frame_items)
        frame_list.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        tk.Label(frame_list, text="Itens do mapeamento", font=("Arial", 9, "bold")).pack(anchor="w")
        
        listbox_map = tk.Listbox(frame_list, width=25, height=12)
        listbox_map.pack(side=tk.LEFT, fill=tk.Y, pady=5)
        
        scrollbar_map = tk.Scrollbar(frame_list, orient=tk.VERTICAL, command=listbox_map.yview)
        scrollbar_map.pack(side=tk.RIGHT, fill=tk.Y)
        listbox_map.config(yscrollcommand=scrollbar_map.set)
        
        frame_edit = tk.Frame(frame_items)
        frame_edit.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        lbl_example = tk.Label(frame_edit, text="", font=("Arial", 8), fg="gray")
        lbl_example.pack(anchor="w", pady=(0, 10))
        
        tk.Label(frame_edit, text="Nome/Identificador:", font=("Arial", 9)).pack(anchor="w")
        entry_name = tk.Entry(frame_edit, font=("Arial", 10))
        entry_name.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(frame_edit, text="Valor:", font=("Arial", 9)).pack(anchor="w")
        text_value = tk.Text(frame_edit, wrap=tk.WORD, height=6, font=("Arial", 10))
        text_value.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        tk.Label(frame_edit, text="💡 Dica: O identificador será usado após o prefixo", 
                font=("Arial", 8), fg="blue", wraplength=300, justify=tk.LEFT).pack(anchor="w", pady=10)
        
        btn_frame = tk.Frame(frame_edit)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        btn_new_map = tk.Button(btn_frame, text="Novo", width=10)
        btn_save_map = tk.Button(btn_frame, text="Salvar", width=10)
        btn_delete_map = tk.Button(btn_frame, text="Excluir", width=10)
        
        btn_new_map.pack(side=tk.LEFT, padx=3)
        btn_save_map.pack(side=tk.LEFT, padx=3)
        btn_delete_map.pack(side=tk.LEFT, padx=3)
        
        def update_example_label():
            mappings = get_mappings_info()
            current_type = mapping_type.get()
            info = mappings.get(current_type, {})
            lbl_example.config(text=f"Exemplo: {info.get('example', '')}")
        
        def refresh_mapping_list():
            listbox_map.delete(0, tk.END)
            current_type = mapping_type.get()
            
            if current_type not in self.snippets:
                self.snippets[current_type] = {}
            
            mapping = self.snippets[current_type]
            if isinstance(mapping, dict):
                for key in sorted(mapping.keys()):
                    if key == "__prefix__":
                        continue
                    listbox_map.insert(tk.END, key)
            
            update_example_label()
        
        def load_selected_mapping(event=None):
            selection = listbox_map.curselection()
            if not selection:
                return
            
            current_type = mapping_type.get()
            key = listbox_map.get(selection[0])
            mapping = self.snippets.get(current_type, {})
            
            entry_name.delete(0, tk.END)
            entry_name.insert(0, key)
            text_value.delete("1.0", tk.END)
            text_value.insert(tk.END, str(mapping.get(key, "")))
        
        def on_type_changed(*args):
            refresh_mapping_list()
            entry_name.delete(0, tk.END)
            text_value.delete("1.0", tk.END)
        
        def on_new_map():
            entry_name.delete(0, tk.END)
            text_value.delete("1.0", tk.END)
            entry_name.focus_set()
        
        def on_save_map():
            mappings = get_mappings_info()
            current_type = mapping_type.get()
            name = entry_name.get().strip()
            value = text_value.get("1.0", tk.END).rstrip("\n").strip()
            
            if not name:
                messagebox.showwarning("Aviso", "Informe um identificador.")
                return
            if not value:
                messagebox.showwarning("Aviso", "Informe um valor.")
                return
            
            if current_type not in self.snippets:
                self.snippets[current_type] = {}
            
            if not isinstance(self.snippets[current_type], dict):
                self.snippets[current_type] = {}
            
            self.snippets[current_type][name] = value
            self.save_snippets(self.snippets)
            
            info = mappings.get(current_type, {})
            prefix = info.get("prefix", "")
            new_trigger_length = len(prefix) + len(name)
            if new_trigger_length > self.max_trigger_length:
                self.max_trigger_length = new_trigger_length
            
            messagebox.showinfo("Sucesso", f"Item '{name}' salvo em {info.get('label', current_type)}.")
            refresh_mapping_list()
        
        def on_delete_map():
            mappings = get_mappings_info()
            current_type = mapping_type.get()
            name = entry_name.get().strip()
            
            if not name:
                messagebox.showwarning("Aviso", "Selecione um item.")
                return
            
            if current_type in self.snippets and isinstance(self.snippets[current_type], dict):
                if name in self.snippets[current_type]:
                    if messagebox.askyesno("Confirmar", f"Excluir '{name}'?"):
                        del self.snippets[current_type][name]
                        self.save_snippets(self.snippets)
                        
                        all_triggers = list(self.snippets.keys())
                        for mapping_key in self.snippets.keys():
                            if mapping_key.startswith("_") and isinstance(self.snippets[mapping_key], dict):
                                info = mappings.get(mapping_key, {})
                                prefix = info.get("prefix", "")
                                for item_name in self.snippets[mapping_key].keys():
                                    all_triggers.append(prefix + item_name)
                        
                        self.max_trigger_length = max(len(t) for t in all_triggers) if all_triggers else 20
                        
                        entry_name.delete(0, tk.END)
                        entry_value.delete(0, tk.END)
                        refresh_mapping_list()
        
        mapping_type.trace("w", on_type_changed)
        listbox_map.bind("<<ListboxSelect>>", load_selected_mapping)
        btn_new_map.configure(command=on_new_map)
        btn_save_map.configure(command=on_save_map)
        btn_delete_map.configure(command=on_delete_map)
        
        refresh_mapping_list()

    def _create_datetime_eco_tab(self, parent):
        """Cria aba de referência para snippets de Data/Hora e Indicadores Econômicos."""
        main = tk.Frame(parent)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Data e Hora ---
        lf_dt = tk.LabelFrame(main, text="Data e Hora", font=("Arial", 9, "bold"))
        lf_dt.pack(fill=tk.X, pady=(0, 10))

        datetime_snippets = [
            ("xhj",       "Data de hoje (DD/MM/AAAA)"),
            ("x-hj",      "Data de hoje (AAAA-MM-DD)"),
            ("xhoje",     "Data por extenso (ex: segunda-feira, 02 de março de 2026)"),
            ("xnow",      "Hora atual (HH:MM:SS)"),
            ("xdatahora", "Data e hora (DD/MM/AAAA às HH:MM)"),
        ]

        for trigger, desc in datetime_snippets:
            row = tk.Frame(lf_dt)
            row.pack(fill=tk.X, padx=10, pady=2)
            tk.Label(row, text=trigger, font=("Consolas", 10, "bold"), fg="#284DB3", width=12, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=desc, font=("Arial", 9), anchor="w").pack(side=tk.LEFT, padx=(10, 0))

        # --- Indicadores Econômicos (BCB) ---
        lf_eco = tk.LabelFrame(main, text="Indicadores Econômicos (Banco Central)", font=("Arial", 9, "bold"))
        lf_eco.pack(fill=tk.BOTH, expand=True)

        eco_snippets = [
            ("xdolar",    "Cotação do dólar (PTAX compra/venda)"),
            ("xselic",    "Taxa Selic meta (% a.a.)"),
            ("xipcam",    "IPCA mensal (%)"),
            ("xipca12",   "IPCA acumulado 12 meses (%)"),
            ("xcdi",      "Taxa CDI acumulada no mês"),
            ("xptax",     "PTAX via SGS"),
            ("xeconomia", "Resumo completo de indicadores"),
        ]

        for trigger, desc in eco_snippets:
            row = tk.Frame(lf_eco)
            row.pack(fill=tk.X, padx=10, pady=2)
            tk.Label(row, text=trigger, font=("Consolas", 10, "bold"), fg="#284DB3", width=12, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=desc, font=("Arial", 9), anchor="w").pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(main, text="Estes snippets são dinâmicos — basta digitar o trigger em qualquer aplicativo.",
                 font=("Arial", 8), fg="gray").pack(anchor="w", pady=(10, 0))

    def _create_stocks_tab(self, parent):
        """Cria aba de referência para snippets de ações (B3 e US)."""
        main = tk.Frame(parent)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(main,
                 text="Ao digitar um destes triggers, um popup pedirá o ticker (ex: PETR4, AAPL).",
                 font=("Arial", 9), fg="#555").pack(anchor="w", pady=(0, 10))

        lf = tk.LabelFrame(main, text="Snippets de Ações", font=("Arial", 9, "bold"))
        lf.pack(fill=tk.BOTH, expand=True)

        # Scrollable frame
        canvas = tk.Canvas(lf, highlightthickness=0)
        scrollbar = tk.Scrollbar(lf, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        stock_snippets = [
            ("xcot",    "Cotação atual"),
            ("xplucro", "P/L (Preço / Lucro)"),
            ("xcap",    "Market Cap (Valor de Mercado)"),
            ("xpvp",    "P/VP (Preço / Valor Patrimonial)"),
            ("xdy",     "Dividend Yield (%)"),
            ("xebt",    "EBITDA"),
            ("xmarg",   "Margem Líquida (%)"),
            ("xroe",    "ROE (Return on Equity)"),
            ("xdivt",   "Dívida Total"),
            ("xdivl",   "Dívida Líquida"),
            ("xcaixa",  "Caixa (Total Cash)"),
            ("xvol",    "Volume Médio Diário"),
            ("xrec",    "Receita Líquida"),
            ("xbeta",   "Beta (volatilidade vs. mercado)"),
            ("x52w",    "Máxima e Mínima de 52 semanas"),
            ("xfund",   "Resumo completo de fundamentos"),
        ]

        for trigger, desc in stock_snippets:
            row = tk.Frame(inner)
            row.pack(fill=tk.X, padx=10, pady=2)
            tk.Label(row, text=trigger, font=("Consolas", 10, "bold"), fg="#284DB3", width=12, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=desc, font=("Arial", 9), anchor="w").pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(main,
                 text="Aceita tickers brasileiros (PETR4, VALE3) e americanos (AAPL, MSFT, GOOGL).",
                 font=("Arial", 8), fg="gray").pack(anchor="w", pady=(10, 0))

    # =====================================================================
    # UI / SYSTEM TRAY
    # =====================================================================

    def create_icon_image(self):
        """Cria um ícone para o system tray"""
        width = 64
        height = 64
        
        if self.enabled:
            bg_color = (40, 77, 179)
            text_color = (255, 255, 255)
        else:
            bg_color = (149, 165, 166)
            text_color = (236, 240, 241)
        
        image = Image.new('RGB', (width, height), bg_color)
        dc = ImageDraw.Draw(image)
        
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            font = ImageFont.load_default()
        
        text = "TXT"
        bbox = dc.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        position = ((width - text_width) // 2, (height - text_height) // 2 - 4)
        
        dc.text(position, text, fill=text_color, font=font)
        
        return image
    
    def toggle_enabled(self, icon, item):
        """Ativa/desativa a expansão de snippets"""
        self.enabled = not self.enabled
        icon.icon = self.create_icon_image()
        status = "ativado" if self.enabled else "desativado"
        icon.notify(f"Text Expander {status}", "Text Expander")
    
    
    def reload_snippets(self, icon, item):
        """Recarrega os snippets do arquivo"""
        try:
            self.snippets = self.load_snippets()
            self.max_trigger_length = max(len(trigger) for trigger in self.snippets.keys()) if self.snippets else 20
            icon.notify("Snippets recarregados com sucesso!", "Text Expander")
        except Exception as e:
            icon.notify(f"Erro ao recarregar: {str(e)}", "Text Expander")
    
    def quit_app(self, icon, item):
        """Encerra o aplicativo"""
        self.enabled = False
        if self.listener:
            self.listener.stop()
        icon.stop()
    
    def run_keyboard_listener(self):
        """Executa o listener do teclado em thread separada"""
        self.listener = keyboard.Listener(on_press=self.on_press)
        self.listener.start()
        self.listener.join()
    
    def run(self):
        """Inicia o programa com system tray"""
        print("=" * 60)
        print("          TEXT EXPANDER - EXPANSOR DE SNIPPETS")
        print("=" * 60)
        
        if self.is_admin():
            print("\n✓ Executando como ADMINISTRADOR")
        else:
            print("\n⚠ Executando SEM privilégios de administrador")
            print("  Funcionará na maioria dos aplicativos comuns")
        
        print("\n📝 Snippets carregados (estáticos, não-callable):")
        static_count = 0
        for trigger, value in self.snippets.items():
            if trigger.startswith("_") or callable(value):
                continue
            static_count += 1
            if static_count <= 5:
                preview = str(value).replace("\n", " ")[:40]
                print(f"  • {trigger:15s} → {preview}")
        
        if static_count > 5:
            print(f"  ... e mais {static_count - 5} snippets estáticos")
        
        dynamic_count = sum(1 for v in self.snippets.values() if callable(v))
        print(f"\n📊 Snippets dinâmicos: {dynamic_count}")
        print(f"   (xhj, xdolar, xcot, xfund, etc.)")
        
        print("\n✓ Ícone adicionado à bandeja do sistema")
        print("  Clique com botão direito no ícone para opções")
        print("=" * 60)
        
        keyboard_thread = threading.Thread(target=self.run_keyboard_listener, daemon=True)
        keyboard_thread.start()
        
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda text: f"{'✓' if self.enabled else '✗'} Ativado",
                self.toggle_enabled,
                checked=lambda item: self.enabled
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Gerenciar Snippets", self.manage_snippets_gui),
            pystray.MenuItem("Recarregar Snippets", self.reload_snippets),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self.quit_app)
        )

        
        self.icon = pystray.Icon(
            "text_expander",
            self.create_icon_image(),
            "Text Expander",
            menu
        )
        
        self.icon.run()


def main():
    """Função principal"""
    expander = TextExpander()
    expander.run()


if __name__ == "__main__":
    main()
