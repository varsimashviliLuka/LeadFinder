"""Pacing and input helpers that make browser actions look like one person's."""

import random
import time


class Human:
    def __init__(self, page, should_stop, rng=None):
        self.page = page
        self.should_stop = should_stop
        self.rng = rng or random.Random()

    def pause(self, low, high=None):
        """Sleep a random time, waking early if the job is cancelled. Returns False if cancelled."""
        remaining = self.rng.uniform(low, high if high is not None else low)
        while remaining > 0:
            if self.should_stop():
                return False
            chunk = min(0.5, remaining)
            if self.page is not None:
                self.page.wait_for_timeout(chunk * 1000)
            else:
                time.sleep(chunk)
            remaining -= chunk
        return not self.should_stop()

    def move_to(self, locator):
        box = locator.bounding_box()
        if not box:
            return None
        x = box["x"] + box["width"] * self.rng.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * self.rng.uniform(0.35, 0.65)
        self.page.mouse.move(x, y, steps=self.rng.randint(8, 22))
        return x, y

    def click(self, locator):
        locator.scroll_into_view_if_needed(timeout=5000)
        self.pause(0.2, 0.6)
        point = self.move_to(locator)
        if point is None:
            locator.click()
            return
        self.pause(0.15, 0.45)
        self.page.mouse.click(*point, delay=self.rng.randint(40, 140))

    def type(self, text):
        for char in text:
            self.page.keyboard.type(char)
            self.page.wait_for_timeout(self.rng.uniform(70, 190))
            if char == " " and self.rng.random() < 0.3:
                self.page.wait_for_timeout(self.rng.uniform(150, 450))

    def scroll(self, locator, rounds=None):
        """Wheel-scroll over an element in a few uneven flicks."""
        self.move_to(locator)
        for _ in range(rounds or self.rng.randint(2, 4)):
            self.page.mouse.wheel(0, self.rng.randint(250, 650))
            if not self.pause(0.6, 1.8):
                return

    def glance(self, locator):
        """Sometimes nudge the detail panel, the way people skim a listing."""
        if self.rng.random() < 0.35:
            self.move_to(locator)
            self.page.mouse.wheel(0, self.rng.randint(120, 400))
            self.pause(0.5, 1.5)
            self.page.mouse.wheel(0, -self.rng.randint(80, 300))
