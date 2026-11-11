"""pygame application shell: window, scene switching, presentation."""
from __future__ import annotations

import pygame

from .fx import LOGICAL_H, LOGICAL_W, Felt, make_overlay
from .menu import MenuScene
from .sprites import Atlas
from .table import GameScene

WINDOW_SIZE = (1280, 720)


class App:
    def __init__(self, bots=2, level="medium", autostart=False):
        pygame.init()
        pygame.display.set_caption("Cambio")
        self.window = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
        self.canvas = pygame.Surface((LOGICAL_W, LOGICAL_H)).convert()
        self.clock = pygame.time.Clock()
        self.atlas = Atlas()
        self.felt = Felt()
        self.overlay = make_overlay()
        self.running = True
        self.menu = MenuScene(self, bots, level)
        self.scene = self.menu
        if autostart:
            self.menu.start()

    def start_game(self, n_bots, level):
        self.menu.n_bots, self.menu.level = n_bots, level
        self.scene = GameScene(self, n_bots, level)

    def go_menu(self):
        self.scene = self.menu

    # ---- window <-> canvas mapping (keeps aspect ratio, letterboxed)
    def _fit(self):
        ww, wh = self.window.get_size()
        s = min(ww / LOGICAL_W, wh / LOGICAL_H)
        w, h = max(1, int(LOGICAL_W * s)), max(1, int(LOGICAL_H * s))
        return s, ((ww - w) // 2, (wh - h) // 2), (w, h)

    def to_canvas(self, pos):
        s, (ox, oy), _ = self._fit()
        return ((pos[0] - ox) / s, (pos[1] - oy) / s)

    def present(self):
        s, off, size = self._fit()
        self.window.fill((8, 14, 16))
        # Integer nearest upscale first keeps pixel edges crisp, then a smooth
        # resample to the exact window size removes harsh stair-stepping.
        k = max(1, int(s) + (1 if s > int(s) else 0))
        img = self.canvas if k == 1 else pygame.transform.scale(self.canvas, (LOGICAL_W * k, LOGICAL_H * k))
        if img.get_size() != size:
            img = pygame.transform.smoothscale(img, size)
        self.window.blit(img, off)
        pygame.display.flip()

    def run(self):
        while self.running:
            dt = min(self.clock.tick(60) / 1000.0, 0.05)
            mouse = self.to_canvas(pygame.mouse.get_pos())
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_F11:
                        pygame.display.toggle_fullscreen()
                    else:
                        self.scene.on_key(e.key)
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button in (1, 3):
                    shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
                    self.scene.on_mouse(self.to_canvas(e.pos), e.button, shift)
            self.felt.update(dt)
            self.scene.update(dt, mouse)
            self.scene.draw(self.canvas, self.atlas, self.felt)
            self.canvas.blit(self.overlay, (0, 0))
            self.present()
        pygame.quit()
