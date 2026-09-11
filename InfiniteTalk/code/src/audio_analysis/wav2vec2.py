from torch import nn

from transformers import Wav2Vec2Config, Wav2Vec2Model
from transformers.modeling_outputs import BaseModelOutput
from transformers.masking_utils import create_bidirectional_mask

from src.audio_analysis.torch_utils import linear_interpolation

# the implementation of Wav2Vec2Model is borrowed from
# https://github.com/huggingface/transformers/blob/HEAD/src/transformers/models/wav2vec2/modeling_wav2vec2.py
# initialize our encoder with the pre-trained wav2vec 2.0 weights.
class Wav2Vec2Model(Wav2Vec2Model):
    """InfiniteTalk audio encoder wrapper.

    Two incompatibilities with transformers >= 5.0 are handled here (the upstream code
    targeted transformers 4.x):

    1. Upstream forced ``self.config.output_attentions = True``, which transformers now
       rejects outright when the attention implementation is ``sdpa``. ``get_embedding``
       only consumes ``hidden_states``, so attention weights are never needed.
    2. ``Wav2Vec2Encoder.forward`` no longer accepts ``output_hidden_states`` and always
       returns just ``last_hidden_state``; the stock ``Wav2Vec2Model.forward`` fills in
       per-layer hidden states through the ``@capture_outputs`` decorator. Because this
       wrapper overrides that forward, the decorator never runs and
       ``embeddings.hidden_states`` came back ``None`` — which broke the audio
       conditioning step entirely. ``_encoder_hidden_states`` reproduces the recorded
       layout explicitly.
    """

    def __init__(self, config: Wav2Vec2Config):
        super().__init__(config)

    def _encoder_hidden_states(self, hidden_states, attention_mask):
        """Run the encoder layers, collecting the output of every layer.

        Returns a list of length ``num_hidden_layers + 1``: index 0 is the
        feature-projection output (before the encoder), then one entry per encoder layer.
        The last entry equals the encoder's ``last_hidden_state``. This matches the
        layout the stock model produces under ``output_hidden_states=True``.
        """
        if attention_mask is not None:
            # make sure padded tokens output 0
            expand_attention_mask = attention_mask.unsqueeze(-1).repeat(1, 1, hidden_states.shape[2])
            hidden_states[~expand_attention_mask] = 0

        attention_mask = create_bidirectional_mask(
            config=self.config,
            inputs_embeds=hidden_states,
            attention_mask=attention_mask,
        )

        position_embeddings = self.encoder.pos_conv_embed(hidden_states)
        hidden_states = hidden_states + position_embeddings.to(hidden_states.device)
        hidden_states = self.encoder.layer_norm(hidden_states)
        hidden_states = self.encoder.dropout(hidden_states)

        collected = [hidden_states]
        for layer in self.encoder.layers:
            hidden_states = layer(hidden_states, attention_mask=attention_mask)
            collected.append(hidden_states)

        return collected

    def forward(
        self,
        input_values,
        seq_len,
        attention_mask=None,
        mask_time_indices=None,
        output_attentions=None,
        output_hidden_states=None,
        return_dict=None,
    ):
        # Keep sdpa valid: attentions are never consumed downstream.
        output_attentions = False

        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        extract_features = self.feature_extractor(input_values)
        extract_features = extract_features.transpose(1, 2)
        extract_features = linear_interpolation(extract_features, seq_len=seq_len)

        if attention_mask is not None:
            # compute reduced attention_mask corresponding to feature vectors
            attention_mask = self._get_feature_vector_attention_mask(
                extract_features.shape[1], attention_mask, add_adapter=False
            )

        hidden_states, extract_features = self.feature_projection(extract_features)
        hidden_states = self._mask_hidden_states(
            hidden_states, mask_time_indices=mask_time_indices, attention_mask=attention_mask
        )

        encoder_hidden_states = self._encoder_hidden_states(hidden_states, attention_mask)
        hidden_states = encoder_hidden_states[-1]

        if self.adapter is not None:
            hidden_states = self.adapter(hidden_states)

        if not return_dict:
            return (hidden_states, encoder_hidden_states)
        return BaseModelOutput(
            last_hidden_state=hidden_states,
            hidden_states=encoder_hidden_states,
        )

    def feature_extract(
        self,
        input_values,
        seq_len,
    ):
        extract_features = self.feature_extractor(input_values)
        extract_features = extract_features.transpose(1, 2)
        extract_features = linear_interpolation(extract_features, seq_len=seq_len)

        return extract_features

    def encode(
        self,
        extract_features,
        attention_mask=None,
        mask_time_indices=None,
        output_attentions=None,
        output_hidden_states=None,
        return_dict=None,
    ):
        # Same as forward(): keep the sdpa attention implementation valid.
        output_attentions = False

        output_hidden_states = (
            output_hidden_states if output_hidden_states is not None else self.config.output_hidden_states
        )
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        if attention_mask is not None:
            # compute reduced attention_mask corresponding to feature vectors
            attention_mask = self._get_feature_vector_attention_mask(
                extract_features.shape[1], attention_mask, add_adapter=False
            )

        hidden_states, extract_features = self.feature_projection(extract_features)
        hidden_states = self._mask_hidden_states(
            hidden_states, mask_time_indices=mask_time_indices, attention_mask=attention_mask
        )

        encoder_hidden_states = self._encoder_hidden_states(hidden_states, attention_mask)
        hidden_states = encoder_hidden_states[-1]

        if self.adapter is not None:
            hidden_states = self.adapter(hidden_states)

        if not return_dict:
            return (hidden_states, encoder_hidden_states)
        return BaseModelOutput(
            last_hidden_state=hidden_states,
            hidden_states=encoder_hidden_states,
        )
