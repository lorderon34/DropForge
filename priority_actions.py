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
