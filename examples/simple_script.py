#!/usr/bin/env python3
"""
Simple example script to test with steptrace CLI.

Run with:
    python -m steptrace run examples/simple_script.py
    python -m steptrace run examples/simple_script.py --log-output STDOUT
    python -m steptrace run examples/simple_script.py --config steptrace.yaml
"""

import sys


def calculate(a, b):
    """Perform some calculations."""
    result = a + b
    squared = result ** 2
    return squared


def process_list(items):
    """Process a list of items."""
    total = 0
    for item in items:
        total += calculate(item, 1)
    return total


class Vector2D:
    """A 2D vector."""
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return f"Vector2D({self.x}, {self.y})"


class Weapon:
    """A weapon with stats."""
    def __init__(self, name, damage):
        self.name = name
        self.damage = damage

    def __repr__(self):
        return f"Weapon({self.name!r}, dmg={self.damage})"


class Sprite:
    """A game sprite with nested objects."""
    def __init__(self, name, x, y, weapon_name="sword", weapon_dmg=10):
        self.name = name
        self.position = Vector2D(x, y)
        self.health = 100
        self.weapon = Weapon(weapon_name, weapon_dmg)

    def move(self, dx, dy):
        self.position.x += dx
        self.position.y += dy

    def __repr__(self):
        return f"Sprite({self.name!r}, pos={self.position})"


def game_step():
    """Simulate a game step with class instances."""
    player = Sprite("hero", 0, 0, "excalibur", 50)
    enemy = Sprite("goblin", 10, 5, "club", 5)
    player.move(3, 4)
    enemy.health -= player.weapon.damage
    print(f"Player: {player}")
    print(f"Enemy health: {enemy.health}")
    return player


def main():
    """Main function."""
    print("Simple script starting...")
    
    x = 10
    y = 20
    z = calculate(x, y)
    print(f"calculate({x}, {y}) = {z}")
    
    items = [1, 2, 3, 4, 5]
    result = process_list(items)
    print(f"process_list({items}) = {result}")
    
    game_step()

    import numpy as np
    x = np.zeros((100, 100))
    
    print("Simple script done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
