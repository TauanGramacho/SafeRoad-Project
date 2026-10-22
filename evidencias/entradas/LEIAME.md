# Entradas usadas nos testes

| Arquivo | Origem | Licença |
|---|---|---|
| `bus.jpg` | Imagem de exemplo da Ultralytics, baixada de https://ultralytics.com/images/bus.jpg | Imagem de demonstração da Ultralytics, usada apenas como entrada de teste |
| `dashcam-oldenburg.mp4` | "Cäcilienbrücke Oldenburg (Dashcam).webm", de Jacek Rużyczka, no Wikimedia Commons: https://commons.wikimedia.org/wiki/File:C%C3%A4cilienbr%C3%BCcke_Oldenburg_(Dashcam).webm | CC BY-SA 4.0 |
| `quadro-9s.jpg` | Quadro do segundo 9 do mesmo vídeo | CC BY-SA 4.0 |

O vídeo original tem 18,6 s em 1920x1080. Para os testes, ele foi convertido para MP4 em 1280x720, sem áudio:

```
ffmpeg -i "Cäcilienbrücke Oldenburg (Dashcam).webm" -vf scale=1280:-2 -an -c:v libx264 -pix_fmt yuv420p dashcam-oldenburg.mp4
ffmpeg -ss 9 -i dashcam-oldenburg.mp4 -frames:v 1 quadro-9s.jpg
```

O MP4 não vai para o Git por causa do tamanho. Quem for repetir os testes precisa baixar o vídeo e rodar os comandos acima.
