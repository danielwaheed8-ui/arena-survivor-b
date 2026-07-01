"""
Temple Run — World-Class Python Edition
=======================================

A pseudo-3D endless runner built on pygame, using the classic OutRun / Jake
Gordon perspective-projection technique for the track, combined with a modern
game-engine architecture:

    * Finite State Machine driven game flow (menu / play / pause / game-over)
    * Publish/subscribe EventBus decoupling systems from each other
    * Object pooling for particles and world entities
    * Procedural, chunk-based, *endless* track generation with biomes
    * Data-driven obstacle / collectible / powerup registries
    * Procedural audio synthesis (SFX + a chiptune music sequencer)
    * Achievements, rotating missions, a coin shop and upgrade tree
    * A difficulty "director" that paces speed and spawn density

The package is intentionally split into small, single-responsibility modules so
the coordinate conventions and public interfaces stay stable as the game grows.

Coordinate conventions (read this before touching the renderer!)
----------------------------------------------------------------
World space is right-handed and measured in "world units":

    * ``x`` — lateral position. 0 is the centre of the road. Negative is left,
      positive is right. The drivable road spans ``[-ROAD_WIDTH, +ROAD_WIDTH]``.
    * ``y`` — elevation. 0 is the road surface at a given segment; larger is up.
    * ``z`` — distance travelled *into* the screen. Always increases as the
      player runs forward. This is the value the whole world is indexed by.

The camera sits slightly behind and above the player and projects world points
onto the screen with a standard pin-hole perspective (see ``render.camera`` and
``render.renderer``). Every module that produces world coordinates must obey
these conventions or the projection will disagree with collision.
"""

__version__ = "2.0.0"
__all__ = ["__version__"]
