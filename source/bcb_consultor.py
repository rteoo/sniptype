"""
Text Expander - Módulo de consulta à API do Banco Central do Brasil
Adicione este código ao arquivo text_expander.pyw existente
"""

import json
from urllib.request import urlopen
from urllib.error import URLError
from datetime import datetime, timedelta

class BCBConsultor:
    """Classe para consultar dados da API do Banco Central do Brasil"""
    
    BASE_URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados/ultimos/1?formato=json"
    BASE_URL_PTAX = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarDia(dataCotacao=@dataCotacao)?@dataCotacao='{}'&$format=json"
    
    # Códigos das séries do SGS (Sistema Gerenciador de Séries Temporais)
    SERIES = {
        'selic_meta': 432,     # Meta Selic definida pelo COPOM
        'ipcam': 433,          # IPCA (% mensal)
        'ipca12': 13522,       # IPCA Variação acumulada em 12 meses (%)
        'cdi': 12,             # Taxa CDI (% Acumulado no mês)
        'ptax': 1,             # Taxa PTAX Compra (R$)
    }
    
    def __init__(self, timeout=5, cache_seconds=300):
        """
        Inicializa o consultor
        
        Args:
            timeout: Tempo máximo de espera pela resposta (segundos)
            cache_seconds: Tempo de cache dos dados (segundos)
        """
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache = {}
    
    def _get_cached_or_fetch(self, key, fetch_func):
        """Retorna dados do cache ou busca novos se expirado"""
        now = datetime.now()
        
        if key in self._cache:
            data, timestamp = self._cache[key]
            if (now - timestamp).total_seconds() < self.cache_seconds:
                return data
        
        try:
            data = fetch_func()
            self._cache[key] = (data, now)
            return data
        except Exception as e:
            # Se falhar, tenta usar cache antigo
            if key in self._cache:
                return self._cache[key][0]
            return f"[Erro: {str(e)}]"
    
    def _fetch_sgs(self, codigo_serie):
        """Busca dados de uma série do SGS"""
        url = self.BASE_URL_SGS.format(codigo_serie)
        with urlopen(url, timeout=self.timeout) as response:
            data = json.loads(response.read().decode())
            if data and len(data) > 0:
                return {
                    'valor': float(data[0]['valor']),
                    'data': data[0]['data']
                }
        return None
    
    def _fetch_dolar(self):
        """Busca cotação do dólar PTAX"""
        # Tenta hoje, se não tiver, tenta dias anteriores
        for days_ago in range(5):
            data = (datetime.now() - timedelta(days=days_ago)).strftime('%m-%d-%Y')
            url = self.BASE_URL_PTAX.format(data)
            
            try:
                with urlopen(url, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode())
                    if 'value' in result and len(result['value']) > 0:
                        cotacao = result['value'][0]
                        return {
                            'compra': float(cotacao['cotacaoCompra']),
                            'venda': float(cotacao['cotacaoVenda']),
                            'data': cotacao['dataHoraCotacao'][:10]
                        }
            except Exception:
                continue
        
        return None
    
    def get_dolar(self):
        """Retorna cotação do dólar formatada"""
        def fetch():
            data = self._fetch_dolar()
            if data:
                return f"US$ 1,00 = R$ {data['venda']:.2f} (compra: R$ {data['compra']:.2f}) - {data['data']}"
            return "[Cotação indisponível]"
        
        return self._get_cached_or_fetch('dolar', fetch)
    
    def get_selic_meta(self):
        """Retorna meta Selic formatada"""
        def fetch():
            data = self._fetch_sgs(self.SERIES['selic_meta'])
            if data:
                return f"Taxa Selic: {data['valor']:.2f}% a.a. (ref: {data['data']})"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('selic_meta', fetch)
    
    def get_ipca_mensal(self):
        """Retorna IPCA mensal formatado"""
        def fetch():
            data = self._fetch_sgs(self.SERIES['ipcam'])
            if data:
                # Converte data de dd/mm/yyyy para mm/yyyy
                data_partes = data['data'].split('/')
                mes_ano = f"{data_partes[1]}/{data_partes[2]}"
                return f"IPCA Mensal: {data['valor']:.2f}% ref. {mes_ano}"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('ipcam', fetch)
    
    def get_ipca_12m(self):
        """Retorna IPCA 12 meses formatado"""
        def fetch():
            data = self._fetch_sgs(self.SERIES['ipca12'])
            if data:
                # Converte data de dd/mm/yyyy para mm/yyyy
                data_partes = data['data'].split('/')
                mes_ano = f"{data_partes[1]}/{data_partes[2]}"
                return f"IPCA 12 Meses: {data['valor']:.2f}% ref. {mes_ano}"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('ipca12', fetch)
    
    def get_cdi(self):
        """Retorna taxa CDI acumulada no mês formatada"""
        def fetch():
            data = self._fetch_sgs(self.SERIES['cdi'])
            if data:
                return f"{data['valor']:.2f}% acum. mês (ref: {data['data']})"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('cdi', fetch)
    
    def get_ptax_sgs(self):
        """Retorna PTAX via SGS formatada"""
        def fetch():
            data = self._fetch_sgs(self.SERIES['ptax'])
            if data:
                return f"R$ {data['valor']:.4f} (ref: {data['data']})"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('ptax_sgs', fetch)
    
    def get_resumo_economico(self):
        """Retorna resumo com vários indicadores"""
        def fetch():
            try:
                dolar = self._fetch_dolar()
                selic = self._fetch_sgs(self.SERIES['selic_meta'])
                ipcam = self._fetch_sgs(self.SERIES['ipcam'])
                ipca12 = self._fetch_sgs(self.SERIES['ipca12'])
                cdi = self._fetch_sgs(self.SERIES['cdi'])
                
                resumo = "📊 INDICADORES ECONÔMICOS\n"
                resumo += "─" * 40 + "\n"
                
                if dolar:
                    resumo += f"💵 Dólar: R$ {dolar['venda']:.2f}\n"
                
                if selic:
                    resumo += f"📈 Selic Meta: {selic['valor']:.2f}% a.a.\n"
                
                if ipcam:
                    resumo += f"📊 IPCA Mensal: {ipcam['valor']:.2f}%\n"
                
                if ipca12:
                    resumo += f"📊 IPCA 12M: {ipca12['valor']:.2f}%\n"
                
                if cdi:
                    resumo += f"💰 CDI: {cdi['valor']:.2f}% (mês)\n"
                
                resumo += f"🕒 Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                
                return resumo
            except Exception as e:
                return f"[Erro ao gerar resumo: {str(e)}]"
        
        return self._get_cached_or_fetch('resumo', fetch)


# Standalone usage example (for manual testing)
if __name__ == "__main__":
    print("=" * 60)
    print("TESTANDO CONSULTAS À API DO BANCO CENTRAL")
    print("=" * 60)
    
    bcb = BCBConsultor()
    
    print("\n💵 Dólar:")
    print(bcb.get_dolar())
    
    print("\n📈 Selic Meta:")
    print(bcb.get_selic_meta())
    
    print("\n📊 IPCA Mensal:")
    print(bcb.get_ipca_mensal())
    
    print("\n📊 IPCA 12 Meses:")
    print(bcb.get_ipca_12m())
    
    print("\n💰 CDI:")
    print(bcb.get_cdi())
    
    print("\n💵 PTAX (SGS):")
    print(bcb.get_ptax_sgs())
    
    print("\n" + "=" * 60)
    print("RESUMO ECONÔMICO")
    print("=" * 60)
    print(bcb.get_resumo_economico())
    
    print("\n✓ Todos os testes concluídos!")