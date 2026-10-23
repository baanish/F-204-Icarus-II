using UnityEngine;

namespace Icarus;

/// <summary>
/// The reheat loop's mix trim. The owner's engine (audio research round 7, take A) keeps reheat +5.25 LU over the dry
/// roar from the side and +8.8 LU from the rear only with +9.53 dB on the reheat after its source volume, which the game
/// sets to afterburner amount x facing and Unity clamps at 1. The file can't carry it: it already peaks at -1.2 dBTP with
/// a 9 dB crest, so 9.5 dB more means clipping it, the distortion the owner rejected in round 4. This scales the float
/// samples instead, which is linear and clean. It sits alone with the reheat source on thrust_vector/afterburner_audio
/// (authored by IcarusAuthor.Audio), so the dry roar and turbine stay at file level.
/// </summary>
sealed class ReheatGain : MonoBehaviour
{
    const float Gain = 2.9957f; // 10^(9.53 / 20)

    void OnAudioFilterRead(float[] data, int channels)
    {
        for (var i = 0; i < data.Length; i++)
        {
            data[i] *= Gain;
        }
    }
}
