"""Version-2 physical CT/RAG oracle and runtime register contract (no hardware I/O)."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import struct, zlib
from frame_codec import crc16, pattern, FrameError

MODES={'CT':1,'RAG':2,'RAG_D':2}
MAX_PAYLOAD=4096
@dataclass(frozen=True)
class Config:
    generation:int=1
    payload_bytes:int=4096
    local_bytes:int=6
    hops:int=2
    mode:int=1
    repetitions:int=128
    period_ticks:int=6250

    def validate(self):
        if any(type(v) is not int for v in asdict(self).values()):raise ValueError('Registers must be integers')
        if self.mode not in (1,2):raise ValueError('mode must be CT=1 or RAG=2')
        if not 0<=self.generation<=0xffffffff:raise ValueError('generation outside uint32')
        if not 1<=self.payload_bytes<=4096:raise ValueError('payload_bytes must be 1..4096')
        if not 1<=self.local_bytes<=1365:raise ValueError('local_bytes must be 1..1365')
        if self.mode==1 and self.payload_bytes<3*self.local_bytes:raise ValueError('CT requires P >= 3*S')
        if not 1<=self.hops<=65535:raise ValueError('hops must be 1..65535')
        if not 0<=self.repetitions<=0xffffffff:raise ValueError('repetitions outside uint32 (0 means continuous)')
        if not 1<=self.period_ticks<=0xffffffff:raise ValueError('period_ticks must be 1..2^32-1')
        return self

    def register(self):
        self.validate()
        words=[self.generation,self.payload_bytes<<16|self.local_bytes,self.mode<<16|self.hops,self.repetitions,self.period_ticks]
        return sum(w<<(32*i) for i,w in enumerate(words))

    @classmethod
    def from_register(cls,word):
        if not 0<=word<1<<160 or word>>88&255:raise ValueError('Invalid reserved config bits')
        return cls(word&0xffffffff,word>>48&65535,word>>32&65535,word>>64&65535,word>>80&255,word>>96&0xffffffff,word>>128&0xffffffff).validate()

    @classmethod
    def from_dict(cls,data):
        data=dict(data)
        if isinstance(data.get('mode'),str):data['mode']=MODES[data['mode']]
        if 'target_modules' in data:
            n=data.pop('target_modules')
            if not 2<=n<=65536:raise ValueError('target_modules must be 2..65536')
            if 'hops' in data and data['hops']!=n-1:raise ValueError('H must equal N-1')
            data['hops']=n-1
        return cls(**data).validate()

def initial_payload(c,origin,trial):
    c.validate()
    if c.mode==2:return pattern(origin,trial,c.payload_bytes)
    return pattern(0,trial,c.local_bytes)+bytes(2*c.local_bytes)+pattern(3,trial,c.payload_bytes)[3*c.local_bytes:]

def encode(c:Config,run:int,trial:int,origin:int):
    c.validate()
    if origin not in range(3) or (c.mode==1 and origin!=0):raise ValueError('Invalid physical source')
    h=struct.pack('>2sBBIIIBBHHHHHHH',b'\xc3\x5a',2,c.mode,c.generation,run,trial,origin,0,
                  c.payload_bytes,c.local_bytes,c.hops,c.hops,0,0,0)
    # The format above includes a placeholder in the final CRC16 field.
    h=h[:30]+crc16(h[:30]).to_bytes(2,'big')
    body=h+initial_payload(c,origin,trial)
    return body+(zlib.crc32(body)&0xffffffff).to_bytes(4,'little')

def inspect(raw:bytes,c:Config):
    if len(raw)!=c.payload_bytes+36:raise FrameError('Length mismatch')
    if raw[:3]!=b'\xc3\x5a\x02' or crc16(raw[:30])!=int.from_bytes(raw[30:32],'big'):raise FrameError('Invalid header')
    mode,generation,run,trial,origin,reserved,p,s,h,left,hop,reserved2=struct.unpack('>BIIIBBHHHHHH',raw[3:30])
    if (mode,generation,p,s,h)!=(c.mode,c.generation,c.payload_bytes,c.local_bytes,c.hops) or origin>2 or reserved or reserved2:
        raise FrameError('Wrong configuration or source')
    if not 1<=left<=h or (mode==2 and hop+left!=h) or (mode==1 and (left!=h or hop!=0 or origin!=0)):
        raise FrameError('Invalid physical hop count')
    return dict(mode=mode,generation=generation,run=run,trial=trial,origin=origin,remaining=left,hop=hop,
                crc_valid=(zlib.crc32(raw[:-4])&0xffffffff)==int.from_bytes(raw[-4:],'little'))

def relay(raw:bytes,c:Config,board:int):
    """Return (outgoing_or_None, input_details); never heal a bad incoming CRC."""
    info=inspect(raw,c)
    if board not in range(3):raise ValueError('Board must be 0,1,2')
    if (c.mode==1 and board==0) or (c.mode==2 and info['remaining']==1):return None,info
    body=bytearray(raw[:-4])
    if c.mode==1:
        offset=32+board*c.local_bytes
        body[offset:offset+c.local_bytes]=pattern(board,info['trial'],c.local_bytes)
    else:
        body[24:26]=(info['remaining']-1).to_bytes(2,'big');body[26:28]=(info['hop']+1).to_bytes(2,'big')
        body[30:32]=crc16(body[:30]).to_bytes(2,'big')
    crc=(zlib.crc32(body)&0xffffffff)^int(not info['crc_valid'])
    return bytes(body)+crc.to_bytes(4,'little'),info
