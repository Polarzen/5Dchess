"""Lightweight variable-candidate policy/value model."""
from __future__ import annotations

from dataclasses import replace

import torch
from torch import nn
import torch.nn.functional as F

from src.training.config import DEFAULT_ENCODING, EncodingConfig, ModelConfig


class PolicyValueModel(nn.Module):
    """Score only canonical legal Action candidates and estimate state value."""

    def __init__(
        self,
        model_config: ModelConfig | None = None,
        encoding_config: EncodingConfig = DEFAULT_ENCODING,
    ) -> None:
        super().__init__()
        self.model_config = model_config or ModelConfig()
        self.encoding_config = encoding_config
        cfg = self.model_config
        enc = encoding_config

        self.board_cnn = nn.Sequential(
            nn.Conv2d(enc.board_channels, cfg.conv_channels, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(cfg.conv_channels, cfg.conv_channels, 3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.board_projection = nn.Sequential(
            nn.Linear(cfg.conv_channels, cfg.board_embedding_dim),
            nn.ReLU(),
        )
        self.board_meta = nn.Sequential(
            nn.Linear(enc.board_meta_dim, cfg.board_meta_hidden_dim),
            nn.ReLU(),
        )
        board_fused = cfg.board_embedding_dim + cfg.board_meta_hidden_dim
        self.board_fuse = nn.Sequential(
            nn.Linear(board_fused, cfg.state_hidden_dim),
            nn.ReLU(),
        )
        self.state_projection = nn.Sequential(
            nn.Linear(cfg.state_hidden_dim * 2 + enc.global_dim, cfg.state_hidden_dim),
            nn.ReLU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(cfg.state_hidden_dim, cfg.state_hidden_dim),
            nn.ReLU(),
        )

        self.move_encoder = nn.Sequential(
            nn.Linear(enc.action_move_feature_dim, cfg.move_hidden_dim),
            nn.ReLU(),
            nn.Linear(cfg.move_hidden_dim, cfg.move_hidden_dim),
            nn.ReLU(),
        )
        self.action_projection = nn.Sequential(
            nn.Linear(cfg.move_hidden_dim * 2 + enc.action_global_dim, cfg.action_hidden_dim),
            nn.ReLU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(cfg.action_hidden_dim, cfg.action_hidden_dim),
            nn.ReLU(),
        )
        self.policy_head = nn.Sequential(
            nn.Linear(cfg.state_hidden_dim + cfg.action_hidden_dim, cfg.joint_hidden_dim),
            nn.ReLU(),
            nn.Dropout(cfg.dropout),
            nn.Linear(cfg.joint_hidden_dim, 1),
        )
        self.value_head = nn.Sequential(
            nn.Linear(cfg.state_hidden_dim, cfg.state_hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(cfg.state_hidden_dim // 2, 1),
            nn.Tanh(),
        )

    @staticmethod
    def _masked_pool(values: torch.Tensor, mask: torch.Tensor, dim: int):
        mask = mask.to(dtype=torch.bool)
        expanded = mask.unsqueeze(-1)
        count = expanded.sum(dim=dim).clamp(min=1)
        mean = (values * expanded.to(values.dtype)).sum(dim=dim) / count.to(values.dtype)
        neg_inf = torch.finfo(values.dtype).min
        maximum = values.masked_fill(~expanded, neg_inf).max(dim=dim).values
        all_masked = ~mask.any(dim=dim)
        if all_masked.any():
            maximum = torch.where(all_masked.unsqueeze(-1), torch.zeros_like(maximum), maximum)
        return mean, maximum

    def encode_state(
        self,
        boards: torch.Tensor,
        board_meta: torch.Tensor,
        board_mask: torch.Tensor,
        global_features: torch.Tensor,
    ) -> torch.Tensor:
        batch, board_count = boards.shape[:2]
        flat = boards.reshape(batch * board_count, *boards.shape[2:])
        visual = self.board_cnn(flat).flatten(1)
        visual = self.board_projection(visual).reshape(batch, board_count, -1)
        meta = self.board_meta(board_meta)
        per_board = self.board_fuse(torch.cat([visual, meta], dim=-1))
        mean, maximum = self._masked_pool(per_board, board_mask, dim=1)
        return self.state_projection(torch.cat([mean, maximum, global_features], dim=-1))

    def encode_actions(
        self,
        action_moves: torch.Tensor,
        action_move_mask: torch.Tensor,
        action_global: torch.Tensor,
    ) -> torch.Tensor:
        batch, candidates, move_count, feature_dim = action_moves.shape
        encoded = self.move_encoder(
            action_moves.reshape(batch * candidates * move_count, feature_dim)
        ).reshape(batch, candidates, move_count, -1)
        mean, maximum = self._masked_pool(encoded, action_move_mask, dim=2)
        return self.action_projection(torch.cat([mean, maximum, action_global], dim=-1))

    def forward(
        self,
        state_boards: torch.Tensor,
        board_meta: torch.Tensor,
        board_mask: torch.Tensor,
        state_global: torch.Tensor,
        action_moves: torch.Tensor,
        action_move_mask: torch.Tensor,
        action_global: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if candidate_mask.ndim != 2:
            raise ValueError("candidate_mask must have shape [batch, candidates]")
        if not candidate_mask.any(dim=1).all():
            raise ValueError("every sample must contain at least one valid candidate")
        state = self.encode_state(state_boards, board_meta, board_mask, state_global)
        actions = self.encode_actions(action_moves, action_move_mask, action_global)
        expanded_state = state.unsqueeze(1).expand(-1, actions.shape[1], -1)
        logits = self.policy_head(torch.cat([expanded_state, actions], dim=-1)).squeeze(-1)
        logits = logits.masked_fill(~candidate_mask.bool(), torch.finfo(logits.dtype).min)
        value = self.value_head(state).squeeze(-1)
        return logits, value

    @property
    def parameter_count(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters())


def policy_value_loss(
    logits: torch.Tensor,
    value: torch.Tensor,
    selected_index: torch.Tensor,
    value_target: torch.Tensor,
    value_mask: torch.Tensor,
    *,
    value_weight: float = 0.5,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    policy = F.cross_entropy(logits, selected_index.long())
    value_mask = value_mask.bool()
    if value_mask.any():
        value_loss = F.smooth_l1_loss(value[value_mask], value_target[value_mask])
    else:
        value_loss = value.sum() * 0.0
    total = policy + float(value_weight) * value_loss
    accuracy = (logits.argmax(dim=1) == selected_index).float().mean()
    return total, {
        "policy_loss": policy.detach(),
        "value_loss": value_loss.detach(),
        "total_loss": total.detach(),
        "policy_accuracy": accuracy.detach(),
    }


__all__ = ["PolicyValueModel", "policy_value_loss"]
