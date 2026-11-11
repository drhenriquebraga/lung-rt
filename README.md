# LUNG RT 1.1.2

Plugin local único para rastreio de nódulos, acesso ao 4D do ContourLab e pré-laudo
experimental sob demanda. Instala em Local Suite completa ou no shell compacto
fornecido pelo instalador. Reutiliza o Python, Torch, fila, seletor e motor da Suite.

- Rastreio: `/lung/rastreio`. Pré-laudos começam **desligados (0)** em cada turno.
- Laudo de TC: `/lung/laudo`, com MPR local e processamento real WebGPU.
- Laudo de raios X: `/lung/laudo/rx`, para radiografia frontal de tórax e rascunho local sob demanda.
- Nódulos e 4D: `/lung/nodulos` e `/lung/4d`, do motor compartilhado.
- A inferência é local. O laudo de TC requer WebGPU; o de raios X usa CPU.
- O piloto int4 requer GPU de pelo menos 6 GB verificada no host, navegador com
  WebGPU e recursos íntegros. Uma P2200 de 5 GB é recusada para pré-laudos.
- Até uma hora por tentativa incluindo preparo; cancelamento, aba perdida,
  truncamento e erro não produzem estado concluído. Nódulos permanecem independentes.
- O texto original, sua tradução e extração literal própria são preservados. Nenhum
  laudo humano é lido pelo NLP. Métricas de lesões vêm apenas da grade nativa do core.
- O PDF DICOM identifica RASCUNHO NÃO VERIFICADO; o SR usa PRELIMINARY/UNVERIFIED.
  Os contornos continuam UNAPPROVED. Não há envio automático DICOM/HL7.
- SQLite permanece em disco local. Backup usa snapshot consistente. Sincronização
  opcional troca eventos idempotentes, mantém conflitos e nunca compartilha SQLite vivo.
  Trabalhos de pré-laudo de outra estação nunca são executados implicitamente.

## Instalação e preparo

O SETUP leve e sua integração pertencem ao host. `module.json` é o contrato do plugin.
`catalog/resource_recipe.json` contém URLs pinadas, tamanhos e SHA256 de todos os
recursos opcionais de pré-laudo. O instalador só os prepara quando escolhidos; os
pesos não fazem parte do código publicado. A política de aceite está em
`catalog/consent.json`; instalação e aplicativo compartilham o mesmo recibo/digest.

## Verificação local

`python tests/test_lung_plugin.py` roda testes sintéticos de API, banco, revisão,
recibos, hardware, estados, sincronização e DICOM. `tests/test_browser.py` usa Chrome
headless contra `tests/ui_server.py`, com volume sintético e sem inferência.
O estado de modelo ausente/hardware insuficiente foi testado. Inferência com pesos
reais depende de uma estação compatível e não é alegada por esses testes.

Documentação do contrato: `docs/HOST_CONTRACT.md`. Licenças: `LICENSE` e `NOTICE`.

### Laudo sintético de raios X

Abra **LUNG RT → Laudo de raios X** para visualizar uma radiografia frontal de tórax e gerar um rascunho experimental para revisão humana. A imagem é processada no computador e o fluxo é separado do laudo de TC.

O preparo opcional do MedGemma 1.5 4B quantizado baixa aproximadamente 3,37 GB de recursos depois do aceite dos termos HAI-DEF. O runtime Windows x64 executa em CPU e não altera o Python, o Torch ou o CUDA da Suite. O instalador leve contém apenas o código e o catálogo com as revisões e hashes dos recursos.

### Pacote para levar

No START HERE, selecione a Local Suite instalada e **Pacote para levar**. A rotina
gera uma pasta e um ZIP equivalente. Ao selecionar os pré-laudos, inclui NVReason
CT INT4 (~3,01 GB) e MedGemma 1.5 4B Q4 para RX (~3,37 GB), total ~6,38 GB.
Arquivos no destino e na Suite escolhida são reutilizados somente quando tamanho
e SHA256 conferem. Python e pesos TotalSegmentator não são incluídos ou baixados
nessa rotina. Leve o ZIP à clínica e selecione-o no instalador principal ou use a
pasta em Configurações → LUNG RT. O recibo de aceite HAI-DEF do MedGemma não é
transferido: o usuário aceita os termos na primeira abertura de RX, inclusive offline.
