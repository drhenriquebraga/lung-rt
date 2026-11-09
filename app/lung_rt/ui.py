from html import escape


def render(runtime,mode):
    import radai_ui as ui
    import radai_menu
    report=mode=="report"
    title="Laudo sintético" if report else "Rastreio populacional de nódulos"
    help_html=ui.ajuda("Pré-laudo experimental — exige revisão médica.",
        "O modelo local int4 pode omitir ou inventar achados. A quantização reduz o tamanho e pode alterar o texto. Versões menos comprimidas existem; superioridade clínica não foi medida aqui.",
        "GPU com pelo menos 6 GB e WebGPU são requisitos do piloto. Sem nuvem nem fallback CPU. Cada tentativa termina em até uma hora; pode falhar ou ser truncada.",
        "Os arquivos são rascunhos novos: PDF DICOM e SR PRELIMINARY/UNVERIFIED. Os contornos continuam UNAPPROVED. O NLP lê somente o próprio rascunho.",direita=True)
    header=ui.cabeca_de_funcao("pulmoes",title,"Processamento local · revisão humana",help_html,chave_modulo="lung")
    marker='<div class="lung-picker-results" id="lung-series"></div>'
    picker=ui.formulario_carregar_imagens("lung_pick",titulo="Adicionar novas séries",
                                        envolver=lambda corpo:corpo+marker)
    page=(runtime.root/"web/page.html").read_text(encoding="utf-8")
    for key,value in {"@TITLE@":escape(title),"@MODE@":mode,"@HEADER@":header,"@PICKER@":picker}.items():
        page=page.replace(key,value)
    apply=runtime.services.get("ui_apply")
    if callable(apply):
        try: return apply(page,"lung_laudo" if report else "lung_rastreio")
        except TypeError: return apply(page)
    return radai_menu.aplicar(ui.com_portao(page),"lung_laudo" if report else "lung_rastreio")
