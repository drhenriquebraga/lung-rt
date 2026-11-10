from html import escape


def _translated_header(ui, title, subtitle, title_key, help_rows, *, attr, label):
    paragraphs = ['<span %s="%s">%s</span>' % (attr, key, escape(text))
                  for key, text in help_rows]
    help_html = ui.ajuda(*paragraphs, direita=True)
    help_html = help_html.replace('aria-label="ajuda"', 'aria-label="ajuda" %s="help"' % label, 1)
    header = ui.cabeca_de_funcao("pulmoes", title, subtitle, help_html, chave_modulo="lung")
    return (header.replace('<span data-radai-frase>', '<span %s="%s">' % (attr, title_key), 1)
                  .replace('class="ui-fn-frase" data-radai-frase', 'class="ui-fn-frase" %s="subtitle"' % attr, 1))


def render(runtime,mode):
    import radai_ui as ui
    import radai_menu
    report=mode=="report"
    title="Laudo sintético" if report else "Rastreio populacional de nódulos"
    help_rows = (
        ("helpLead", "Pré-laudo experimental — exige revisão médica."),
        ("helpModel", "O modelo local int4 pode omitir ou inventar achados. A quantização reduz o tamanho e pode alterar o texto. Versões menos comprimidas existem. A superioridade clínica não foi medida aqui."),
        ("helpRuntime", "O piloto requer WebGPU e uma GPU com pelo menos 6 GB. Sem nuvem nem fallback CPU. Cada tentativa termina em até uma hora e pode falhar ou ser truncada."),
        ("helpDraft", "Os arquivos são rascunhos novos: PDF DICOM e SR PRELIMINARY/UNVERIFIED. Os contornos continuam UNAPPROVED. O NLP lê somente o próprio rascunho."),
    )
    header = _translated_header(ui, title, "Processamento local · revisão humana",
                                "reportTitle" if report else "screeningTitle", help_rows,
                                attr="data-lung-key", label="data-lung-title")
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


def render_xray(runtime):
    import radai_ui as ui
    import radai_menu

    title = "Laudo sintético · Raios X"
    subtitle = "Radiografia de tórax · processamento local"
    help_rows = (
        ("helpWarning", "O pré-laudo experimental pode omitir ou inventar achados e exige revisão médica."),
        ("helpLocal", "Selecione uma radiografia frontal de tórax. A imagem e o rascunho ficam nesta estação."),
    )
    header = _translated_header(ui, title, subtitle, "title", help_rows,
                                attr="data-rx-text", label="data-rx-label")
    page = (runtime.root / "web/xray.html").read_text(encoding="utf-8")
    page = page.replace("@HEADER@", header)
    apply = runtime.services.get("ui_apply")
    if callable(apply):
        try:
            return apply(page, "lung_laudo_rx")
        except TypeError:
            return apply(page)
    return radai_menu.aplicar(ui.com_portao(page), "lung_laudo_rx")
