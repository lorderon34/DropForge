def add_game_to_priority(
    game_name: str,
    priority_games: list[str],
    excluded_games: set[str],
) -> bool:
    """Add a game once unless it is explicitly excluded."""
    if not game_name or game_name in priority_games or game_name in excluded_games:
        return False
    priority_games.append(game_name)
    return True


def remove_game_from_priority(game_name: str, priority_games: list[str]) -> bool:
    """Remove the game, including duplicate entries in old settings."""
    if game_name not in priority_games:
        return False
    priority_games[:] = [name for name in priority_games if name != game_name]
    return True
