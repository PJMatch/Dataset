import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import * as FileSystem from 'expo-file-system/legacy';
import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import KeyEvent from 'react-native-keyevent';

export default function App() {
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const [micPermission, requestMicPermission] = useMicrophonePermissions();

  const cameraRef = useRef(null);
  const scrollViewRef = useRef(null);

  const [isRecording, setIsRecording] = useState(false);
  const [recordedUri, setRecordedUri] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [showSuccessMessage, setShowSuccessMessage] = useState(false);

  const [serverUrl, setServerUrl] = useState('');
  const [personId, setPersonId] = useState('');
  const [sentenceId, setSentenceId] = useState('');
  const [sentenceText, setSentenceText] = useState('');
  const [mode, setMode] = useState('csv');
  const [sentencesDict, setSentencesDict] = useState({});

  const [uploadMode, setUploadMode] = useState('queue');
  const [queue, setQueue] = useState([]);
  const [isUploadingBackground, setIsUploadingBackground] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);

  const [lastKeyCode, setLastKeyCode] = useState(null);

  const stateRef = useRef({
    isRecording,
    recordedUri,
    isUploading,
    serverUrl,
    personId,
    sentenceId,
    sentenceText,
    mode,
    uploadMode,
  });

  useEffect(() => {
    stateRef.current = {
      isRecording,
      recordedUri,
      isUploading,
      serverUrl,
      personId,
      sentenceId,
      sentenceText,
      mode,
      uploadMode,
    };
  }, [
    isRecording,
    recordedUri,
    isUploading,
    serverUrl,
    personId,
    sentenceId,
    sentenceText,
    mode,
    uploadMode,
  ]);

  // Auto-scroll w dół po ZAKOŃCZENIU nagrywania
  useEffect(() => {
    if (recordedUri && scrollViewRef.current) {
      setTimeout(() => {
        scrollViewRef.current.scrollToEnd({ animated: true });
      }, 200);
    }
  }, [recordedUri]);

  // WORKER KOLEJKI (Tło)
  useEffect(() => {
    const processQueue = async () => {
      if (queue.length === 0 || isUploadingBackground) return;

      setIsUploadingBackground(true);
      const item = queue[0];
      const cleanUrl = item.serverUrl.replace(/\/$/, '');
      const formData = new FormData();
      
      formData.append('person_id', item.personId);
      formData.append('sentence_id', item.sentenceId);
      formData.append('sentence', item.sentenceText);
      formData.append('video', {
        uri: item.uri,
        name: 'recording.mp4',
        type: 'video/mp4',
      });

      try {
        const response = await fetch(`${cleanUrl}/upload`, {
          method: 'POST',
          body: formData,
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        
        if (response.ok) {
          await FileSystem.deleteAsync(item.uri, { idempotent: true });
          setUploadedCount((c) => c + 1);
        }
      } catch (error) {
        console.warn('Błąd tła:', error);
      } finally {
        setQueue((prev) => prev.slice(1));
        setIsUploadingBackground(false);
      }
    };
    
    processQueue();
  }, [queue, isUploadingBackground]);

  const fetchSentences = () => {
    if (!serverUrl) return Alert.alert('Błąd', 'Wklej link!');
    
    fetch(`${serverUrl.replace(/\/$/, '')}/sentences`)
      .then((res) => res.json())
      .then((data) => {
        setSentencesDict(data);
        Alert.alert('Sukces', 'Baza pobrana!');
      })
      .catch(() => Alert.alert('Błąd', 'Nie połączono.'));
  };

  useEffect(() => {
    if (mode === 'csv' && sentenceId) {
      const formattedId = String(Number(sentenceId)).padStart(2, '0');
      setSentenceText(
        sentencesDict[formattedId] ||
        sentencesDict[sentenceId] ||
        'Nie znaleziono zdania!'
      );
    }
  }, [sentenceId, mode, sentencesDict]);

  // PILOT
  useEffect(() => {
    KeyEvent.onKeyDownListener((keyEvent) => {
      setLastKeyCode(keyEvent.keyCode);
      const s = stateRef.current;
      const ACTION_KEY = 24; // Zdefiniowany przycisk głośności (Volume Up)

      if (keyEvent.keyCode === ACTION_KEY) {
        if (s.isRecording) {
          stopRecording();
        } else if (s.recordedUri) {
          handleSendAction();
        } else {
          startRecording();
        }
      }
    });
    
    return () => KeyEvent.removeKeyDownListener();
  }, []);

  const startRecording = () => {
    const s = stateRef.current;
    if (
      !s.personId ||
      (!s.sentenceId && s.mode === 'csv') ||
      !s.sentenceText ||
      s.sentenceText === 'Nie znaleziono zdania!'
    ) return;
    
    if (cameraRef.current) {
      setIsRecording(true);
      cameraRef.current
        .recordAsync({ maxDuration: 60 })
        .then((data) => setRecordedUri(data.uri))
        .catch((err) => Alert.alert('Błąd', err.message))
        .finally(() => setIsRecording(false));
    }
  };

  const stopRecording = () => cameraRef.current?.stopRecording();

  // Akcja "Wysyłania"
  const handleSendAction = async () => {
    const s = stateRef.current;
    if (!s.recordedUri || !s.serverUrl) return;

    // Trzymamy widok na samym dole
    scrollViewRef.current?.scrollToEnd({ animated: true });

    if (s.uploadMode === 'queue') {
      // TRYB KOLEJKI
      setQueue((prev) => [
        ...prev,
        {
          uri: s.recordedUri,
          personId: s.personId,
          sentenceId: s.sentenceId,
          sentenceText: s.sentenceText,
          serverUrl: s.serverUrl,
        },
      ]);

      setRecordedUri(null);
      if (s.sentenceId && s.mode === 'csv') {
        setSentenceId(String(Number(s.sentenceId) + 1));
      }

      setShowSuccessMessage(true);
      setTimeout(() => setShowSuccessMessage(false), 500);
    } else {
      // TRYB BEZPOŚREDNI
      setIsUploading(true);
      const formData = new FormData();
      
      formData.append('person_id', s.personId);
      formData.append('sentence_id', s.sentenceId);
      formData.append('sentence', s.sentenceText);
      formData.append('video', {
        uri: s.recordedUri,
        name: 'recording.mp4',
        type: 'video/mp4',
      });

      try {
        const res = await fetch(`${s.serverUrl.replace(/\/$/, '')}/upload`, {
          method: 'POST',
          body: formData,
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        
        if (res.ok) {
          await FileSystem.deleteAsync(s.recordedUri, { idempotent: true });
          setRecordedUri(null);
          if (s.sentenceId && s.mode === 'csv') {
            setSentenceId(String(Number(s.sentenceId) + 1));
          }

          setShowSuccessMessage(true);
          setTimeout(() => setShowSuccessMessage(false), 800);
        }
      } catch (e) {
        Alert.alert('Błąd sieci');
      } finally {
        setIsUploading(false);
      }
    }
  };

  const retakeVideo = async () => {
    if (recordedUri) {
      await FileSystem.deleteAsync(recordedUri, { idempotent: true });
      setRecordedUri(null);
      scrollViewRef.current?.scrollToEnd({ animated: true });
    }
  };

  if (!cameraPermission || !micPermission) {
    return (
      <View style={styles.container}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: '#f5f5f5' }}>
      <ScrollView
        ref={scrollViewRef}
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.serverConfigBox}>
          <TextInput
            style={styles.input}
            value={serverUrl}
            onChangeText={setServerUrl}
            placeholder="Link serwera"
            placeholderTextColor="#000000"
            keyboardType="url"
            autoCapitalize="none"
          />
          <TouchableOpacity style={styles.button} onPress={fetchSentences}>
            <Text style={styles.buttonText}>Połącz i pobierz bazę</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.queuePanel}>
          <Text style={styles.label}>Tryb pracy:</Text>
          <View style={{ flexDirection: 'row', marginBottom: 10 }}>
            <TouchableOpacity
              style={[styles.modeBtn, uploadMode === 'direct' && styles.activeMode]}
              onPress={() => setUploadMode('direct')}
            >
              <Text style={{ color: uploadMode === 'direct' ? 'white' : 'black' }}>
                Pojedynczy
              </Text>
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.modeBtn, uploadMode === 'queue' && styles.activeMode]}
              onPress={() => setUploadMode('queue')}
            >
              <Text style={{ color: uploadMode === 'queue' ? 'white' : 'black' }}>
                Kolejka
              </Text>
            </TouchableOpacity>
          </View>
          
          {uploadMode === 'queue' && (
            <View style={styles.statsBox}>
              <Text style={{ color: '#E65100', fontWeight: 'bold' }}>
                W kolejce: {queue.length}
              </Text>
              <Text style={{ color: '#1B5E20', fontWeight: 'bold' }}>
                Wysłane: {uploadedCount}
              </Text>
            </View>
          )}
        </View>

        <View style={styles.row}>
          <View style={{ flex: 1, marginRight: 5 }}>
            <Text style={styles.label}>Osoba:</Text>
            <TextInput
              style={styles.input}
              value={personId}
              onChangeText={setPersonId}
              keyboardType="numeric"
            />
          </View>
          <View style={{ flex: 1, marginLeft: 5 }}>
            <Text style={styles.label}>Zdanie ID:</Text>
            <TextInput
              style={styles.input}
              value={sentenceId}
              onChangeText={setSentenceId}
              keyboardType="numeric"
            />
          </View>
        </View>

        <Text style={styles.label}>Treść:</Text>
        <TextInput
          style={[styles.input, styles.textArea]}
          value={sentenceText}
          editable={mode === 'custom'}
          onChangeText={setSentenceText}
          multiline
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
              <Text style={{ color: '#ccc' }}>Wybierz akcję pilota lub przycisk</Text>
            </View>
          )}
        </View>

        {isUploading ? (
          <View style={styles.uploadingBox}>
            <ActivityIndicator size="large" color="#2196F3" />
            <Text>Wysyłanie...</Text>
          </View>
        ) : recordedUri ? (
          <View style={styles.actionRow}>
            <TouchableOpacity
              style={[styles.actionBtn, { backgroundColor: '#FF9800' }]}
              onPress={retakeVideo}
            >
              <Text style={styles.buttonText}>🔄 Powtórz</Text>
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.actionBtn, { backgroundColor: '#4CAF50' }]}
              onPress={handleSendAction}
            >
              <Text style={styles.buttonText}>⬆️ Wyślij</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <TouchableOpacity
            style={[styles.recordBtn, isRecording ? styles.recordingBtn : null]}
            onPress={isRecording ? stopRecording : startRecording}
          >
            <Text style={styles.recordBtnText}>
              {isRecording ? '⏹ Zatrzymaj' : '🔴 Nagraj'}
            </Text>
          </TouchableOpacity>
        )}
      </ScrollView>

      {/* Pływająca nakładka sukcesu */}
      {showSuccessMessage && (
        <View style={styles.successOverlay}>
          <Text style={styles.successText}>✅ Zapisano!</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    padding: 15,
  },
  serverConfigBox: {
    backgroundColor: '#e3e3e3',
    padding: 10,
    borderRadius: 8,
    marginBottom: 10,
  },
  queuePanel: {
    backgroundColor: '#e3e3e3',
    padding: 10,
    borderRadius: 8,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#ccc',
  },
  statsBox: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    backgroundColor: 'white',
    padding: 8,
    borderRadius: 5,
  },
  successOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(232, 245, 233, 0.95)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1000,
  },
  successText: {
    fontSize: 40,
    fontWeight: 'bold',
    color: '#4CAF50',
  },
  label: {
    fontSize: 13,
    fontWeight: 'bold',
    marginBottom: 3,
  },
  input: {
    backgroundColor: 'white',
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#ccc',
    marginBottom: 8,
    color: 'black',
  },
  textArea: {
    height: 100,
    textAlignVertical: 'top',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  modeBtn: {
    flex: 1,
    padding: 8,
    borderWidth: 1,
    borderColor: '#ccc',
    alignItems: 'center',
    borderRadius: 5,
    marginHorizontal: 2,
  },
  activeMode: {
    backgroundColor: '#2196F3',
    borderColor: '#2196F3',
  },
  cameraContainer: {
    width: '100%',
    aspectRatio: 3 / 4,
    borderRadius: 10,
    overflow: 'hidden',
    marginBottom: 15,
    backgroundColor: 'black',
  },
  camera: {
    flex: 1,
  },
  overlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cropGuide: {
    width: '75%',
    aspectRatio: 1,
    borderWidth: 3,
    borderColor: 'rgba(0, 255, 0, 0.8)',
  },
  recordedPreviewBox: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#333',
  },
  previewTitle: {
    color: 'white',
    fontSize: 18,
    fontWeight: 'bold',
  },
  recordBtn: {
    backgroundColor: '#E53935',
    padding: 20,
    borderRadius: 8,
    alignItems: 'center',
  },
  recordingBtn: {
    backgroundColor: '#757575',
  },
  recordBtnText: {
    color: 'white',
    fontSize: 20,
    fontWeight: 'bold',
  },
  button: {
    backgroundColor: '#2196F3',
    padding: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonText: {
    color: 'white',
    fontWeight: 'bold',
  },
  uploadingBox: {
    alignItems: 'center',
    padding: 10,
  },
  actionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  actionBtn: {
    flex: 1,
    padding: 20,
    borderRadius: 8,
    alignItems: 'center',
    marginHorizontal: 5,
  },
});