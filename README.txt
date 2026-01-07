Arquivos corrigidos (para o app não fechar logo após a tela de loading)

O que foi feito:
1) tibia_tools.kv: trocado `<MoreItem@OneLineIconListItem>:` por `<MoreItem>:`
2) main.py: o carregamento do KV agora usa `resource_find()` (mais seguro no Android) e,
   se houver erro, imprime o Traceback no logcat e mostra uma mensagem na tela.

Como aplicar:
- Substitua os arquivos `main.py` e `tibia_tools.kv` do seu projeto por estes aqui.
- Depois rode:
    buildozer android clean
    buildozer -v android debug deploy run logcat

Se ainda fechar, copie o bloco do Traceback que aparece no logcat.
