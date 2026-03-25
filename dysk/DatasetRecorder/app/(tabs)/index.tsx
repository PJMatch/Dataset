/**
 * Main screen of the DatasetRecorder mobile app.
 * Handles video recording, camera preview, crop guide overlay,
 * and uploading files to the FastAPI server.
 */
import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import * as FileSystem from 'expo-file-system/legacy';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';

// Your URL
const BACKEND_URL = 'https://suites-ranking-supervisors-herbal.trycloudflare.com';

export default function App() {
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const [micPermission, requestMicPermission] = useMicrophonePermissions();
  
  const cameraRef = useRef(null);
  
  const [isRecording, setIsRecording] = useState(false);
  const [recordedUri, setRecordedUri] = useState<string | null>(null); 
  const [isUploading, setIsUploading] = useState(false);
  const [showSuccessMessage, setShowSuccessMessage] = useState(false); 
  
  const [personId, setPersonId] = useState('');
  const [sentenceId, setSentenceId] = useState('');
  const [sentenceText, setSentenceText] = useState('');
  const [mode, setMode] = useState('csv');
  
  const [sentencesDict, setSentencesDict] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch(`${BACKEND_URL}/sentences`)
      .then(res => res.json())
      .then(data => setSentencesDict(data))
      .catch(err => console.error("Error fetching sentences:", err));
  }, []);

  useEffect(() => {
    if (mode === 'csv' && sentenceId) {
      const formattedId = String(Number(sentenceId)).padStart(2, '0');
      if (sentencesDict[formattedId]) {
        setSentenceText(sentencesDict[formattedId]);
      } else if (sentencesDict[sentenceId]) {
        setSentenceText(sentencesDict[sentenceId]);
      } else {
        setSentenceText('Nie znaleziono zdania!');
      }
    }
  }, [sentenceId, mode, sentencesDict]);

  if (!cameraPermission || !micPermission) {
    return <View style={styles.container}><ActivityIndicator size="large" /></View>;
  }

  if (!cameraPermission.granted || !micPermission.granted) {
    return (
      <View style={styles.container}>
        <Text style={styles.permissionText}>Aplikacja wymaga dostępu do kamery i mikrofonu.</Text>
        <TouchableOpacity style={styles.button} onPress={() => { requestCameraPermission(); requestMicPermission(); }}>
          <Text style={styles.buttonText}>Przyznaj uprawnienia</Text>
        </TouchableOpacity>
      </View>
    );
  }

  /**
   * Starts video recording with a maximum duration limit.
   */
  const startRecording = async () => {
    if (!personId || (!sentenceId && mode === 'csv') || !sentenceText || sentenceText === 'Nie znaleziono zdania!') {
      Alert.alert('Błąd', 'Uzupełnij poprawnie wszystkie dane przed nagraniem.');
      return;
    }

    if (cameraRef.current) {
      setIsRecording(true);
      try {
        const videoRecordPromise = cameraRef.current.recordAsync({ maxDuration: 60 });
        const data = await videoRecordPromise;
        setRecordedUri(data.uri); 
      } catch (error: any) {
        Alert.alert('Błąd nagrywania', error.message);
      } finally {
        setIsRecording(false);
      }
    }
  };

  /**
   * Stops the currently active recording.
   */
  const stopRecording = () => {
    if (cameraRef.current && isRecording) {
      cameraRef.current.stopRecording();
    }
  };

  /**
   * Uploads the recorded video to the FastAPI server using FormData.
   */
  const uploadVideo = async () => {
    if (!recordedUri) return;
    
    setIsUploading(true);
    const formData = new FormData();
    formData.append('person_id', personId);
    formData.append('sentence_id', sentenceId);
    formData.append('sentence', sentenceText);
    
    formData.append('video', {
      uri: recordedUri,
      name: 'recording.mp4',
      type: 'video/mp4',
    } as any);

    try {
      const response = await fetch(`${BACKEND_URL}/upload`, {
        method: 'POST',
        body: formData,
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      if (response.ok) {
        await FileSystem.deleteAsync(recordedUri, { idempotent: true });
        setShowSuccessMessage(true);
        setRecordedUri(null);
        
        if (sentenceId && mode === 'csv') {
          setSentenceId(String(Number(sentenceId) + 1));
        }

        setTimeout(() => setShowSuccessMessage(false), 1500);
      } else {
        Alert.alert('Błąd serwera', 'Coś poszło nie tak podczas wysyłania.');
      }
    } catch (error: any) {
      Alert.alert('Błąd sieci', error.message);
    } finally {
      setIsUploading(false);
    }
  };

  /**
   * Deletes the current recording from device memory and allows the user to retake the video.
   */
  const retakeVideo = async () => {
    if (recordedUri) {
      await FileSystem.deleteAsync(recordedUri, { idempotent: true });
      setRecordedUri(null);
    }
  };

  if (showSuccessMessage) {
    return (
      <View style={[styles.container, styles.successContainer]}>
        <Text style={styles.successText}>✅ Wysłano!</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>Dodaj nagranie</Text>

      <Text style={styles.label}>ID osoby (np. 01):</Text>
      <TextInput style={styles.input} value={personId} onChangeText={setPersonId} placeholder="Wpisz ID" keyboardType="numeric" />

      <View style={styles.row}>
        <TouchableOpacity style={[styles.modeBtn, mode === 'csv' && styles.activeMode]} onPress={() => { setMode('csv'); setSentenceText(''); }}>
          <Text style={{color: mode === 'csv' ? 'white' : 'black'}}>Z bazy (ID)</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[styles.modeBtn, mode === 'custom' && styles.activeMode]} onPress={() => { setMode('custom'); setSentenceId(''); setSentenceText(''); }}>
          <Text style={{color: mode === 'custom' ? 'white' : 'black'}}>Własne</Text>
        </TouchableOpacity>
      </View>

      {mode === 'csv' && (
        <>
          <Text style={styles.label}>ID zdania:</Text>
          <TextInput style={styles.input} value={sentenceId} onChangeText={setSentenceId} placeholder="Wpisz ID zdania (np. 1)" keyboardType="numeric" />
        </>
      )}

      <Text style={styles.label}>Treść zdania:</Text>
      <TextInput 
        style={[styles.input, styles.textArea]} 
        value={sentenceText} 
        onChangeText={setSentenceText} 
        editable={mode === 'custom'} 
        multiline 
        placeholder={mode === 'custom' ? "Wpisz swoje zdanie tutaj..." : ""} 
      />

      <View style={styles.cameraContainer}>
        {!recordedUri ? (
          <CameraView style={styles.camera} mode="video" facing="back" ref={cameraRef}>
            <View style={styles.overlay} pointerEvents="none">
              <View style={styles.cropGuide} />
            </View>
          </CameraView>
        ) : (
          <View style={styles.recordedPreviewBox}>
            <Text style={styles.previewTitle}>Nagranie zarejestrowane</Text>
            <Text style={styles.previewSubtitle}>Wybierz akcję poniżej</Text>
          </View>
        )}
      </View>

      {isUploading ? (
        <View style={styles.uploadingBox}>
          <ActivityIndicator size="large" color="#2196F3" />
          <Text style={styles.uploadingText}>Wysyłanie na serwer...</Text>
        </View>
      ) : recordedUri ? (
        <View style={styles.actionRow}>
          <TouchableOpacity style={[styles.actionBtn, { backgroundColor: '#FF9800' }]} onPress={retakeVideo}>
            <Text style={styles.buttonText}>🔄 Powtórz</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.actionBtn, { backgroundColor: '#4CAF50' }]} onPress={uploadVideo}>
            <Text style={styles.buttonText}>⬆️ Wyślij</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <TouchableOpacity 
          style={[styles.recordBtn, isRecording ? styles.recordingBtn : null]} 
          onPress={isRecording ? stopRecording : startRecording}
        >
          <Text style={styles.recordBtnText}>{isRecording ? "⏹ Zatrzymaj" : "🔴 Nagraj"}</Text>
        </TouchableOpacity>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flexGrow: 1, padding: 20, backgroundColor: '#f5f5f5', justifyContent: 'center' },
  successContainer: { justifyContent: 'center', alignItems: 'center', backgroundColor: '#e8f5e9' },
  successText: { fontSize: 32, fontWeight: 'bold', color: '#4CAF50', textAlign: 'center' },
  permissionText: { textAlign: 'center', marginBottom: 20 },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 20, textAlign: 'center' },
  label: { fontSize: 16, fontWeight: 'bold', marginBottom: 5 },
  input: { backgroundColor: 'white', padding: 12, borderRadius: 8, borderWidth: 1, borderColor: '#ccc', marginBottom: 15, fontSize: 16 },
  textArea: { height: 80, textAlignVertical: 'top' },
  row: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 15 },
  modeBtn: { flex: 1, padding: 10, borderWidth: 1, borderColor: '#ccc', alignItems: 'center', borderRadius: 5, marginHorizontal: 5 },
  activeMode: { backgroundColor: '#2196F3', borderColor: '#2196F3' },
  cameraContainer: { width: '100%', aspectRatio: 3 / 4, borderRadius: 10, overflow: 'hidden', marginBottom: 20, backgroundColor: 'black' },
  camera: { flex: 1 },
  overlay: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  cropGuide: { width: '75%', aspectRatio: 1, borderWidth: 3, borderColor: 'rgba(0, 255, 0, 0.8)' },
  recordedPreviewBox: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#333' },
  previewTitle: { color: 'white', fontSize: 20, fontWeight: 'bold' },
  previewSubtitle: { color: '#aaa', marginTop: 10 },
  recordBtn: { backgroundColor: '#E53935', padding: 18, borderRadius: 8, alignItems: 'center' },
  recordingBtn: { backgroundColor: '#757575' },
  recordBtnText: { color: 'white', fontSize: 18, fontWeight: 'bold' },
  button: { backgroundColor: '#2196F3', padding: 15, borderRadius: 8, alignItems: 'center' },
  buttonText: { color: 'white', fontSize: 16, fontWeight: 'bold' },
  uploadingBox: { alignItems: 'center', padding: 20 },
  uploadingText: { marginTop: 10, fontSize: 16 },
  actionRow: { flexDirection: 'row', justifyContent: 'space-between' },
  actionBtn: { flex: 1, padding: 18, borderRadius: 8, alignItems: 'center', marginHorizontal: 5 }
});