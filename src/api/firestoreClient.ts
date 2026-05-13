import { initializeApp, type FirebaseOptions } from 'firebase/app';
import { collection, getFirestore, onSnapshot, query, type DocumentData } from 'firebase/firestore';

const config: FirebaseOptions | undefined = import.meta.env.VITE_FIREBASE_API_KEY
  ? {
      apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
      authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
      projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID
    }
  : undefined;

export const firebaseApp = config ? initializeApp(config) : null;
export const firestore = firebaseApp ? getFirestore(firebaseApp) : null;

export function listenToCollection(path: string, onItems: (items: DocumentData[]) => void) {
  if (!firestore) {
    onItems([]);
    return () => undefined;
  }
  return onSnapshot(query(collection(firestore, path)), (snapshot) => {
    onItems(snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() })));
  });
}
