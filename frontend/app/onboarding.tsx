import { useState } from 'react'
import {
  View, Text, TouchableOpacity, StyleSheet,
  ScrollView, Alert, SafeAreaView,
} from 'react-native'
import { router } from 'expo-router'
import { supabase } from '../lib/supabase'
import { NEEDS } from '../constants/needs'
import { Colors } from '../constants/colors'

const EMOTIONS = [
  { value: 1, emoji: '😔', label: 'In grief' },
  { value: 2, emoji: '😟', label: 'Heavy' },
  { value: 3, emoji: '😐', label: 'Neutral' },
  { value: 4, emoji: '🙂', label: 'Hopeful' },
  { value: 5, emoji: '😊', label: 'Joyful' },
]

export default function Onboarding() {
  const [step, setStep] = useState<1 | 2>(1)
  const [emotionalState, setEmotionalState] = useState<number | null>(null)
  const [selectedNeeds, setSelectedNeeds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)

  function toggleNeed(id: number) {
    setSelectedNeeds(prev =>
      prev.includes(id) ? prev.filter(n => n !== id) : [...prev, id]
    )
  }

  async function finish() {
    if (!emotionalState) return
    setLoading(true)

    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setLoading(false); return }

    // Mark any existing current state as not current
    await supabase
      .from('reading_state')
      .update({ is_current: false })
      .eq('user_id', user.id)
      .eq('is_current', true)

    const { error } = await supabase.from('reading_state').insert({
      user_id: user.id,
      emotional_state: emotionalState,
      active_need_ids: selectedNeeds,
      is_current: true,
    })

    setLoading(false)
    if (error) {
      Alert.alert('Error', error.message)
      return
    }
    router.replace('/(main)/recommendations')
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.inner} showsVerticalScrollIndicator={false}>

        {step === 1 && (
          <>
            <Text style={styles.stepLabel}>Step 1 of 2</Text>
            <Text style={styles.heading}>How are you feeling right now?</Text>
            <Text style={styles.subheading}>
              Folio matches books to where you actually are, not where you wish you were.
            </Text>

            <View style={styles.emotionRow}>
              {EMOTIONS.map(e => (
                <TouchableOpacity
                  key={e.value}
                  style={[styles.emotionTile, emotionalState === e.value && styles.emotionTileSelected]}
                  onPress={() => setEmotionalState(e.value)}
                >
                  <Text style={styles.emotionEmoji}>{e.emoji}</Text>
                  <Text style={[styles.emotionLabel, emotionalState === e.value && styles.emotionLabelSelected]}>
                    {e.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <TouchableOpacity
              style={[styles.button, !emotionalState && styles.buttonDisabled]}
              onPress={() => emotionalState && setStep(2)}
              disabled={!emotionalState}
            >
              <Text style={styles.buttonText}>Next</Text>
            </TouchableOpacity>
          </>
        )}

        {step === 2 && (
          <>
            <Text style={styles.stepLabel}>Step 2 of 2</Text>
            <Text style={styles.heading}>What are you looking for?</Text>
            <Text style={styles.subheading}>
              Pick any that feel true right now. You can skip this if nothing fits.
            </Text>

            <View style={styles.needsGrid}>
              {NEEDS.map(need => {
                const selected = selectedNeeds.includes(need.id)
                return (
                  <TouchableOpacity
                    key={need.id}
                    style={[styles.needTile, selected && styles.needTileSelected]}
                    onPress={() => toggleNeed(need.id)}
                  >
                    <Text style={styles.needEmoji}>{need.emoji}</Text>
                    <Text style={[styles.needLabel, selected && styles.needLabelSelected]}>
                      {need.shortLabel}
                    </Text>
                  </TouchableOpacity>
                )
              })}
            </View>

            <TouchableOpacity
              style={[styles.button, loading && styles.buttonDisabled]}
              onPress={finish}
              disabled={loading}
            >
              <Text style={styles.buttonText}>{loading ? 'Setting up…' : 'Show my books'}</Text>
            </TouchableOpacity>

            <TouchableOpacity onPress={() => setStep(1)} style={styles.backButton}>
              <Text style={styles.backText}>← Back</Text>
            </TouchableOpacity>
          </>
        )}

      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  inner: { padding: 28, paddingTop: 48 },
  stepLabel: { fontSize: 13, color: Colors.textMuted, marginBottom: 10, fontWeight: '500', letterSpacing: 0.5, textTransform: 'uppercase' },
  heading: { fontSize: 28, fontWeight: '800', color: Colors.text, marginBottom: 12, lineHeight: 36, letterSpacing: -0.5 },
  subheading: { fontSize: 15, color: Colors.textMuted, lineHeight: 22, marginBottom: 36 },

  // Emotion picker
  emotionRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 48 },
  emotionTile: {
    flex: 1,
    alignItems: 'center',
    padding: 12,
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: Colors.border,
    marginHorizontal: 3,
    backgroundColor: Colors.surface,
  },
  emotionTileSelected: { borderColor: Colors.primary, backgroundColor: Colors.tag },
  emotionEmoji: { fontSize: 28, marginBottom: 6 },
  emotionLabel: { fontSize: 11, color: Colors.textMuted, textAlign: 'center' },
  emotionLabelSelected: { color: Colors.primary, fontWeight: '600' },

  // Needs grid
  needsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 40 },
  needTile: {
    width: '47%',
    flexDirection: 'row',
    alignItems: 'center',
    padding: 14,
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: Colors.border,
    backgroundColor: Colors.surface,
    gap: 10,
  },
  needTileSelected: { borderColor: Colors.primary, backgroundColor: Colors.tag },
  needEmoji: { fontSize: 22 },
  needLabel: { fontSize: 13, color: Colors.text, flex: 1, flexWrap: 'wrap' },
  needLabelSelected: { color: Colors.primary, fontWeight: '600' },

  button: {
    backgroundColor: Colors.primary,
    borderRadius: 14,
    padding: 18,
    alignItems: 'center',
    marginBottom: 16,
  },
  buttonDisabled: { opacity: 0.4 },
  buttonText: { color: '#FFFFFF', fontSize: 17, fontWeight: '700' },
  backButton: { alignItems: 'center', padding: 12 },
  backText: { color: Colors.textMuted, fontSize: 15 },
})
